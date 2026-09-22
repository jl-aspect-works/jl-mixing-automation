#!/usr/bin/env python3
"""Plan and stage JL Mixing v1.1 final-delivery packages."""
from __future__ import annotations
import argparse, fnmatch, hashlib, json, os, re, shutil, stat, sys
from pathlib import Path, PurePosixPath

class DeliveryError(Exception): pass

def split_patterns(values):
    out=[]
    for value in values:
        for item in value.split(','):
            item=item.strip()
            if not item: raise DeliveryError('Empty include/exclude pattern is not allowed')
            out.append(item)
    return out

def normalize(name):
    return re.sub(r'[\s_-]+',' ',name.casefold()).strip()

def has_word(text, word):
    return re.search(rf'(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])', text) is not None

def classify(name):
    text=normalize(name)
    if has_word(text,'stem') or has_word(text,'stems'): return 'stems'
    if has_word(text,'instrumental'): return 'instrumental'
    if has_word(text,'acapella') or re.search(r'(?<![a-z0-9])a cappella(?![a-z0-9])',text): return 'acapella'
    if re.search(r'(?<![a-z0-9])tv mix(?![a-z0-9])',text): return 'tv_mix'
    if re.search(r'(?<![a-z0-9])performance mix(?![a-z0-9])',text): return 'performance_mix'
    if has_word(text,'master'): return 'master'
    if re.search(r'(?<![a-z0-9])main mix(?![a-z0-9])',text): return 'main_mix'
    return 'unclassified'

def load_json(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,UnicodeError,json.JSONDecodeError) as e: raise DeliveryError(f'Unable to read JSON {path}: {e}')

def safe_relative(value):
    if not isinstance(value,str) or not value or '\\' in value: raise DeliveryError(f'Unsafe delivery path: {value!r}')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in ('','.','..') for x in value.split('/')): raise DeliveryError(f'Unsafe delivery path: {value}')
    return p

def regular_no_symlink(path):
    try: mode=path.lstat().st_mode
    except OSError: return False
    return stat.S_ISREG(mode) and not path.is_symlink()

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def recursive_listing(root):
    if not root.exists(): return []
    result=[]
    for p in sorted(root.rglob('*'), key=lambda x:x.relative_to(root).as_posix().casefold()):
        result.append(p.relative_to(root).as_posix() + ('/' if p.is_dir() and not p.is_symlink() else ''))
    return result

def plan(args):
    revision=Path(args.revision_dir)
    delivery=Path(args.delivery_dir)
    includes=split_patterns(args.include)
    excludes=split_patterns(args.exclude)
    selected=[]; excluded=[]
    if not revision.is_dir() or revision.is_symlink(): raise DeliveryError(f'Revision directory is missing or unsafe: {revision}')
    for item in sorted(revision.iterdir(), key=lambda p:p.name.casefold()):
        if item.name == 'Revision_Notes.md':
            excluded.append({'name':item.name,'reason':'revision notes'}); continue
        if item.is_symlink(): raise DeliveryError(f'Symbolic links are not allowed in a delivery source: {item}')
        if item.is_dir(): raise DeliveryError(f'Subdirectories are not allowed in a delivery source: {item}')
        if not regular_no_symlink(item): raise DeliveryError(f'Unsupported source item: {item}')
        if args.working_prefix and item.name.startswith(args.working_prefix):
            excluded.append({'name':item.name,'reason':'working prefix'}); continue
        if includes and not any(fnmatch.fnmatchcase(item.name,p) for p in includes):
            excluded.append({'name':item.name,'reason':'include pattern'}); continue
        if excludes and any(fnmatch.fnmatchcase(item.name,p) for p in excludes):
            excluded.append({'name':item.name,'reason':'exclude pattern'}); continue
        kind=classify(item.name)
        rel=f'Stems/{item.name}' if kind=='stems' else item.name
        selected.append({'source':str(item),'name':item.name,'deliverable_type':kind,'path':rel})
    if not selected: raise DeliveryError('No deliverable files were found after applying filters')
    seen={}
    for rec in selected:
        key=rec['path'].casefold()
        if key in seen: raise DeliveryError(f"Case-insensitive destination collision: {seen[key]} and {rec['path']}")
        seen[key]=rec['path']
    manifest_path=delivery/'delivery-manifest.json'
    old_files=[]
    if args.mode=='default':
        if manifest_path.exists() or manifest_path.is_symlink(): raise DeliveryError('A final-delivery package already exists. Use --overwrite or --clean')
        for rec in selected:
            dest=delivery.joinpath(*safe_relative(rec['path']).parts)
            if dest.exists() or dest.is_symlink(): raise DeliveryError(f'Destination is already occupied: {dest}')
        if args.zip_name and ((delivery/args.zip_name).exists() or (delivery/args.zip_name).is_symlink()): raise DeliveryError(f'ZIP destination already exists: {delivery/args.zip_name}')
    elif args.mode=='overwrite':
        if not regular_no_symlink(manifest_path): raise DeliveryError('--overwrite requires a valid prior delivery manifest')
        old=load_json(manifest_path)
        old_files=[r['path'] for r in old.get('files',[]) if isinstance(r,dict) and 'path' in r]
        old_map={p.casefold():p for p in old_files}; new_map={r['path'].casefold():r['path'] for r in selected}
        if set(old_map)!=set(new_map):
            missing=sorted(set(old_map)-set(new_map))
            extra=sorted(set(new_map)-set(old_map))
            details=[]
            if missing: details.append('stale prior files: '+', '.join(old_map[k] for k in missing))
            if extra: details.append('new paths not present in prior package: '+', '.join(new_map[k] for k in extra))
            raise DeliveryError('--overwrite requires the same delivery path set; use --clean ('+'; '.join(details)+')')
        for rec in selected:
            dest=delivery.joinpath(*safe_relative(rec['path']).parts)
            if (dest.exists() or dest.is_symlink()) and rec['path'].casefold() not in old_map:
                raise DeliveryError(f'Destination is occupied by an untracked item: {dest}')
        z=delivery/args.project_zip_name
        if (z.exists() or z.is_symlink()) and not args.zip_name:
            raise DeliveryError('An existing generated ZIP would become stale; use --zip or --clean')
    deletions=recursive_listing(delivery) if args.mode=='clean' else []
    requested=load_json(args.project_manifest)['delivery']['requested_deliverables']
    fixed=['stems','instrumental','acapella','tv_mix','performance_mix','master','main_mix','unclassified']
    order=[]
    for x in requested+fixed:
        if x not in order: order.append(x)
    rank={x:i for i,x in enumerate(order)}
    selected.sort(key=lambda r:(rank.get(r['deliverable_type'],999),r['path'].casefold(),r['path']))
    data={'selected':selected,'excluded':excluded,'deletions':deletions,'old_files':old_files,'mode':args.mode}
    Path(args.output).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

def copy_tree_no_follow(src,dst):
    if not src.exists(): return
    for item in src.iterdir():
        target=dst/item.name
        if item.is_symlink(): os.symlink(os.readlink(item),target)
        elif item.is_dir(): shutil.copytree(item,target,symlinks=True)
        elif regular_no_symlink(item): shutil.copy2(item,target,follow_symlinks=False)
        else: raise DeliveryError(f'Unsupported existing delivery item: {item}')

def build(args):
    plan_data=load_json(args.plan)
    project=load_json(args.project_manifest)
    stage=Path(args.stage_dir); current=Path(args.delivery_dir)
    if any(stage.iterdir()): raise DeliveryError(f'Staging directory is not empty: {stage}')
    if plan_data['mode']!='clean': copy_tree_no_follow(current,stage)
    else:
        (stage/'Stems').mkdir(parents=True,exist_ok=True)
        shutil.copy2(args.delivery_notes_template,stage/'Delivery_Notes.md')
    stems_dir=stage/'Stems'
    if stems_dir.exists() or stems_dir.is_symlink():
        if not stems_dir.is_dir() or stems_dir.is_symlink():
            raise DeliveryError(f'Stems path is unsafe: {stems_dir}')
    else:
        stems_dir.mkdir(parents=True)
    notes=stage/'Delivery_Notes.md'
    if notes.exists() or notes.is_symlink():
        if not regular_no_symlink(notes):
            raise DeliveryError(f'Delivery notes path is unsafe: {notes}')
    else:
        shutil.copy2(args.delivery_notes_template,notes)
    manifest=stage/'delivery-manifest.json'
    if manifest.exists() or manifest.is_symlink():
        if manifest.is_dir() and not manifest.is_symlink(): shutil.rmtree(manifest)
        else: manifest.unlink()
    if plan_data['mode']=='overwrite':
        for rel in plan_data['old_files']:
            p=stage.joinpath(*safe_relative(rel).parts)
            if p.exists() or p.is_symlink():
                if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
                else: p.unlink()
        z=stage/args.project_zip_name
        if z.exists() or z.is_symlink():
            if z.is_dir() and not z.is_symlink(): shutil.rmtree(z)
            else: z.unlink()
    records=[]
    for rec in plan_data['selected']:
        src=Path(rec['source'])
        if not regular_no_symlink(src): raise DeliveryError(f'Source changed or became unsafe: {src}')
        before=sha256(src)
        dest=stage.joinpath(*safe_relative(rec['path']).parts)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() or dest.is_symlink():
            if plan_data['mode']=='default': raise DeliveryError(f'Staged destination conflict: {dest}')
            if dest.is_dir() and not dest.is_symlink(): shutil.rmtree(dest)
            else: dest.unlink()
        shutil.copy2(src,dest,follow_symlinks=False)
        after=sha256(dest)
        if before!=after: raise DeliveryError(f'Copy verification failed: {src}')
        records.append({'path':rec['path'],'deliverable_type':rec['deliverable_type'],'size_bytes':dest.stat().st_size,'sha256':after})
    number=project['state']['approved_revision']
    rev=next(r for r in project['revisions'] if r['number']==number)
    doc={
      'metadata':{'schema':'mixing-delivery','schema_version':'1.1.0','document_id':args.document_id,'created_with':args.created_with,'created_at':args.created_at},
      'project':{'project_document_id':project['metadata']['document_id'],'project_id':project['project_id'],'project_name':project['project_name']},
      'client':{'client_document_id':project['client']['client_document_id'],'client_id':project['client']['client_id']},
      'revision':{'number':number,'revision_id':rev['revision_id'],'description':rev['description'],'approval':rev['approval']},
      'delivery':{'method':project['delivery']['method']},'files':records}
    manifest.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')

def parser():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('plan'); a.add_argument('--revision-dir',required=True); a.add_argument('--delivery-dir',required=True); a.add_argument('--project-manifest',required=True); a.add_argument('--mode',choices=['default','overwrite','clean'],required=True); a.add_argument('--working-prefix',default='WORK '); a.add_argument('--include',action='append',default=[]); a.add_argument('--exclude',action='append',default=[]); a.add_argument('--zip-name',default=''); a.add_argument('--project-zip-name',required=True); a.add_argument('--output',required=True)
    b=sub.add_parser('build'); b.add_argument('--plan',required=True); b.add_argument('--project-manifest',required=True); b.add_argument('--delivery-dir',required=True); b.add_argument('--stage-dir',required=True); b.add_argument('--delivery-notes-template',required=True); b.add_argument('--document-id',required=True); b.add_argument('--created-with',required=True); b.add_argument('--created-at',required=True); b.add_argument('--project-zip-name',required=True)
    return p

def main():
    args=parser().parse_args()
    try:
        plan(args) if args.cmd=='plan' else build(args)
        return 0
    except (DeliveryError,OSError,KeyError,StopIteration,ValueError) as e:
        print(f'Error: {e}',file=sys.stderr); return 5
if __name__=='__main__': raise SystemExit(main())
