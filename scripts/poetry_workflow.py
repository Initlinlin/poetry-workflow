#!/usr/bin/env python3
"""Local poem workflow bookkeeping. No API calls, credentials, or model emulation."""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from book_extract import extract


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_text(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        return stream.read()


def write_text(path, text, exclusive=False):
    with Path(path).open('x' if exclusive else 'w', encoding='utf-8', newline='') as stream:
        stream.write(text)


def save_manifest(run, data):
    tmp = run / 'manifest.json.tmp'
    write_text(tmp, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(run / 'manifest.json')


def local_path(run, relative):
    path = (run / relative).resolve()
    if run not in path.parents:
        raise ValueError('清单路径必须位于运行目录内部')
    return path


def load_manifest(run):
    run = Path(run).resolve()
    data = json.loads(read_text(run / 'manifest.json'))
    if data.get('schema_version') != 1 or not data.get('sources') or not data.get('chunks'):
        raise ValueError('无效或空的运行清单')
    return run, data


def parts(text, budget):
    start = 0
    while start < len(text):
        end = min(start + budget, len(text))
        if end < len(text):
            cut = text.rfind('\n', start + budget // 2, end)
            if cut >= 0:
                end = cut + 1
        yield start, end, text[start:end]
        start = end


def prepare(args):
    run = Path(args.run_dir).resolve()
    if run.exists():
        raise ValueError('运行目录已存在；使用新目录，或继续已有清单')
    if not 100 <= args.chunk_chars <= 100000:
        raise ValueError('chunk-chars 必须在 100 到 100000 之间')
    inputs = [Path(p).resolve() for p in args.sources]
    if len(set(inputs)) != len(inputs):
        raise ValueError('重复选择了同一个文件')
    for path in inputs:
        if not path.is_file() or path.suffix.lower() not in ('.txt', '.md', '.epub', '.docx', '.pdf'):
            raise ValueError('需要明确的 TXT/MD/EPUB/DOCX/PDF 文件列表：' + str(path))
        if path.name.lower() == 'server.md':
            raise ValueError('server.md 为部署记录，不是诗歌输入')
        if path.stat().st_size > 50_000_000:
            raise ValueError('输入文件超过 50 MB，先拆分：' + path.name)
    run.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.poetry-prepare-', dir=str(run.parent)))
    data = {'schema_version': 1, 'run_id': uuid.uuid4().hex,
            'sources': [], 'chunks': [], 'read': {}}
    try:
        for folder in ('sources', 'chunks', 'notes'):
            (stage / folder).mkdir()
        for index, path in enumerate(inputs, 1):
            raw = path.read_bytes()
            parsed = extract(raw, path.name)
            text = parsed['text']
            source_id = 'source-%04d' % index
            snapshot = 'sources/' + source_id + '.txt'
            write_text(stage / snapshot, text)
            data['sources'].append({'id': source_id, 'title': path.stem,
                                    'original_path': str(path), 'raw_sha256': digest(raw),
                                    'snapshot': snapshot, 'sha256': digest(text.encode('utf-8')),
                                    'characters': len(text), 'warnings': parsed['warnings']})
            for number, (start, end, body) in enumerate(parts(text, args.chunk_chars), 1):
                chunk_id = '%s-%04d' % (source_id, number)
                relative = 'chunks/' + chunk_id + '.txt'
                write_text(stage / relative, body)
                data['chunks'].append({'id': chunk_id, 'source_id': source_id,
                                       'start': start, 'end': end, 'path': relative,
                                       'sha256': digest(body.encode('utf-8'))})
        save_manifest(stage, data)
        stage.rename(run)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {'run_dir': str(run), 'sources': len(inputs), 'chunks': len(data['chunks']),
            'characters': sum(s['characters'] for s in data['sources']),
            'warnings': {s['id']: s['warnings'] for s in data['sources'] if s['warnings']}}


def verify(run, data, require_read=True):
    source_ids = [s['id'] for s in data['sources']]
    chunk_ids = [c['id'] for c in data['chunks']]
    if len(set(source_ids)) != len(source_ids) or len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError('清单含重复标识')
    if any(c['source_id'] not in source_ids for c in data['chunks']):
        raise ValueError('片段来源不存在')
    for source in data['sources']:
        text = read_text(local_path(run, source['snapshot']))
        if len(text) != source['characters'] or digest(text.encode('utf-8')) != source['sha256']:
            raise ValueError('阅读快照被修改：' + source['id'])
        position, collected = 0, []
        chunks = [c for c in data['chunks'] if c['source_id'] == source['id']]
        for chunk in chunks:
            body = read_text(local_path(run, chunk['path']))
            if chunk['start'] != position or chunk['end'] <= position:
                raise ValueError('片段有遗漏、重叠或顺序异常：' + chunk['id'])
            if chunk['end'] - position != len(body) or digest(body.encode('utf-8')) != chunk['sha256']:
                raise ValueError('片段内容被修改：' + chunk['id'])
            collected.append(body)
            position = chunk['end']
        if position != len(text) or ''.join(collected) != text:
            raise ValueError('片段未完整覆盖来源：' + source['id'])
    missing = []
    for chunk in data['chunks']:
        receipt = data['read'].get(chunk['id'])
        if not receipt:
            missing.append(chunk['id'])
            continue
        note = read_text(local_path(run, receipt['note']))
        if not note.strip() or digest(note.encode('utf-8')) != receipt['sha256']:
            raise ValueError('阅读笔记为空或登记后被修改：' + chunk['id'])
    if require_read and missing:
        raise ValueError('仍有 %d 个片段未登记阅读：%s' % (len(missing), ', '.join(missing)))
    return {'sources': len(source_ids), 'chunks': len(chunk_ids),
            'read_chunks': len(chunk_ids) - len(missing), 'complete': not missing}


def record(args):
    run, data = load_manifest(args.run_dir)
    verify(run, data, require_read=False)
    if args.chunk_id not in {c['id'] for c in data['chunks']}:
        raise ValueError('片段 ID 不在清单中')
    if args.chunk_id in data['read']:
        raise ValueError('片段已登记，原有笔记保留')
    note = read_text(args.note)
    if not note.strip():
        raise ValueError('阅读笔记不能为空')
    relative = 'notes/' + args.chunk_id + '.md'
    write_text(local_path(run, relative), note, exclusive=True)
    data['read'][args.chunk_id] = {'note': relative, 'sha256': digest(note.encode('utf-8'))}
    save_manifest(run, data)
    return verify(run, data, require_read=False)


def safe_component(value):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f\[\]#]', '_', value).strip('. ')[:80]
    if not value:
        raise ValueError('标题或文件夹不能为空')
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % i for i in range(1, 10)), *('LPT%d' % i for i in range(1, 10))}:
        value = '_' + value
    return value


def new_markdown(folder, stem, text):
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(10000):
        path = folder / (stem + ('-%d' % index if index else '') + '.md')
        try:
            write_text(path, text, exclusive=True)
            return path
        except FileExistsError:
            pass
    raise ValueError('同名文件过多，请修改标题')


def save(args):
    run, data = load_manifest(args.run_dir)
    verify(run, data)
    blueprint = read_text(run / 'blueprint.md')
    poem = read_text(args.poem)
    if not blueprint.strip() or not poem.strip():
        raise ValueError('蓝图和诗歌正文不能为空')
    vault = Path(args.vault).resolve()
    if (vault / '.poetry-vault.json').exists():
        raise ValueError('网站索引诗库请使用导入功能；本脚本仅写普通 Markdown 诗库')
    pieces = Path(args.folder).parts
    if not pieces or Path(args.folder).is_absolute() or any(p in ('.', '..') for p in pieces):
        raise ValueError('输出文件夹应为诗库内的相对路径')
    target = vault.joinpath(*(safe_component(p) for p in pieces)).resolve()
    record_folder = (vault / '创作笔记').resolve()
    for folder in (target, record_folder):
        if vault not in folder.parents:
            raise ValueError('输出目录不能通过符号链接越出诗库')
    title = safe_component(args.title)
    report = '# ' + args.title + ' · 阅读与蓝图\n\n' + blueprint + '\n\n## 来源\n'
    for source in data['sources']:
        report += '\n- %s：%s（%d 字符）\n' % (source['id'], source['title'], source['characters'])
        for warning in source['warnings']:
            report += '  - 提取提示：' + warning + '\n'
    for chunk in data['chunks']:
        report += '\n## ' + chunk['id'] + '\n\n' + read_text(local_path(run, data['read'][chunk['id']]['note'])) + '\n'
    record_path = new_markdown(record_folder, title + '--阅读记录', report)
    now = datetime.now(timezone.utc).isoformat()
    headers = {'title': args.title, 'tags': args.tag or [], 'createdAt': now, 'runId': data['run_id']}
    frontmatter = '---\n' + ''.join(k + ': ' + json.dumps(v, ensure_ascii=False) + '\n' for k, v in headers.items()) + '---\n\n'
    poem_path = new_markdown(target, title, frontmatter + poem + '\n\n创作记录：[[' + record_path.stem + ']]\n')
    return {'poem': str(poem_path), 'reading_record': str(record_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='读取全部选中文件，生成快照和无损分块')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--sources', nargs='+', required=True)
    p.add_argument('--chunk-chars', type=int, default=6000)
    p.set_defaults(handler=prepare)
    p = sub.add_parser('record', help='登记已真实阅读的片段和分析笔记')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--chunk-id', required=True)
    p.add_argument('--note', required=True)
    p.set_defaults(handler=record)
    p = sub.add_parser('check', help='核验全量覆盖与阅读登记')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(handler=lambda args: verify(*load_manifest(args.run_dir)))
    p = sub.add_parser('save', help='保存新诗及完整阅读记录，不覆盖旧作品')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--poem', required=True)
    p.add_argument('--vault', required=True)
    p.add_argument('--title', required=True)
    p.add_argument('--folder', default='创作/融合诗')
    p.add_argument('--tag', action='append')
    p.set_defaults(handler=save)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(args.handler(args), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('错误：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
