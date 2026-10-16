import argparse
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import poetry_workflow as workflow
from book_extract import extract


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        self.source = self.root / 'selected.txt'
        self.text = '开头\r\n' + '甲乙丙丁\n' * 90 + '全部内容的最后一行'
        workflow.write_text(self.source, self.text)

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, paths=None):
        workflow.prepare(argparse.Namespace(run_dir=str(self.run), sources=paths or [str(self.source)], chunk_chars=100))
        return workflow.load_manifest(self.run)

    def complete(self):
        self.prepare()
        _, data = workflow.load_manifest(self.run)
        for chunk in data['chunks']:
            note = self.root / 'note.md'
            workflow.write_text(note, '合成测试笔记：片段 %s，从 %d 至 %d。' % (chunk['id'], chunk['start'], chunk['end']))
            workflow.record(argparse.Namespace(run_dir=str(self.run), chunk_id=chunk['id'], note=str(note)))
        workflow.write_text(self.run / 'blueprint.md', '合成测试蓝图：所有块均有登记。')
        poem = self.root / 'draft.txt'
        workflow.write_text(poem, '新写的一行\n另一行\n')
        return argparse.Namespace(run_dir=str(self.run), poem=str(poem), vault=str(self.root / 'output'), title='测试标题', folder='创作/融合诗', tag=['测试'])

    def test_lossless_unicode_and_line_endings(self):
        run, data = self.prepare()
        rebuilt = ''.join(workflow.read_text(run / c['path']) for c in data['chunks'])
        self.assertEqual(rebuilt, self.text)
        self.assertTrue(rebuilt.endswith('全部内容的最后一行'))
        self.assertEqual(len(rebuilt), data['sources'][0]['characters'])
        self.assertFalse(workflow.verify(run, data, require_read=False)['complete'])

    def test_unbroken_long_lines_and_multiple_sources(self):
        workflow.write_text(self.source, '🌙' * 999 + '终')
        other = self.root / 'other.md'
        workflow.write_text(other, '# 第二个来源\n全部保留')
        run, data = self.prepare([str(self.source), str(other)])
        for source in data['sources']:
            body = ''.join(workflow.read_text(run / c['path']) for c in data['chunks'] if c['source_id'] == source['id'])
            self.assertEqual(body, workflow.read_text(run / source['snapshot']))
        self.assertEqual(len(data['sources']), 2)

    def test_incomplete_reading_cannot_save(self):
        self.prepare()
        poem = self.root / 'poem.txt'
        workflow.write_text(poem, '正文')
        args = argparse.Namespace(run_dir=str(self.run), poem=str(poem), vault=str(self.root / 'out'), title='标题', folder='创作', tag=[])
        with self.assertRaisesRegex(ValueError, '未登记阅读'):
            workflow.save(args)
        self.assertFalse((self.root / 'out').exists())

    def test_modified_chunk_is_detected(self):
        run, data = self.prepare()
        workflow.write_text(run / data['chunks'][-1]['path'], '被改过')
        with self.assertRaisesRegex(ValueError, '片段内容被修改'):
            workflow.verify(run, data, require_read=False)

    def test_omitted_chunk_is_detected(self):
        run, data = self.prepare()
        data['chunks'].pop()
        with self.assertRaisesRegex(ValueError, '未完整覆盖'):
            workflow.verify(run, data, require_read=False)

    def test_atomic_prepare_failure(self):
        empty = self.root / 'empty.md'
        workflow.write_text(empty, '')
        with self.assertRaises(ValueError):
            self.prepare([str(self.source), str(empty)])
        self.assertFalse(self.run.exists())
        self.assertEqual(list(self.root.glob('.poetry-prepare-*')), [])

    def test_save_preserves_existing_works_and_links_actual_record(self):
        args = self.complete()
        original = self.root / 'output' / '创作' / '融合诗' / '测试标题.md'
        original.parent.mkdir(parents=True)
        workflow.write_text(original, '保留的旧稿')
        first = workflow.save(args)
        second = workflow.save(args)
        self.assertEqual(workflow.read_text(original), '保留的旧稿')
        self.assertNotEqual(first['poem'], second['poem'])
        self.assertNotEqual(first['reading_record'], second['reading_record'])
        self.assertIn('[[' + Path(second['reading_record']).stem + ']]', workflow.read_text(second['poem']))
        self.assertTrue(workflow.verify(*workflow.load_manifest(self.run))['complete'])

    def test_modified_reading_note_is_detected(self):
        self.complete()
        run, data = workflow.load_manifest(self.run)
        receipt = next(iter(data['read'].values()))
        workflow.write_text(run / receipt['note'], '修改了笔记')
        with self.assertRaisesRegex(ValueError, '笔记为空或登记后被修改'):
            workflow.verify(run, data)

    def test_indexed_app_vault_is_not_modified(self):
        args = self.complete()
        vault = Path(args.vault)
        vault.mkdir()
        workflow.write_text(vault / '.poetry-vault.json', '{}')
        with self.assertRaisesRegex(ValueError, '网站索引诗库'):
            workflow.save(args)
        self.assertEqual(list(vault.iterdir()), [vault / '.poetry-vault.json'])

    def test_epub_preserves_non_linear_and_unspined_documents(self):
        path = self.root / 'synthetic.epub'
        with zipfile.ZipFile(path, 'w') as book:
            book.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
            book.writestr('book.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                          '<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
                          '<item id="b" href="b.xhtml" media-type="application/xhtml+xml"/>'
                          '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
                          '<spine><itemref idref="a"/><itemref idref="b" linear="no"/></spine></package>')
            for letter in 'abc':
                book.writestr(letter + '.xhtml', '<p>正文-' + letter + '</p>')
        result = extract(path.read_bytes(), path.name)
        for letter in 'abc':
            self.assertEqual(result['text'].count('正文-' + letter), 1)

    def test_docx_extracts_main_body_and_reports_scope(self):
        path = self.root / 'synthetic.docx'
        with zipfile.ZipFile(path, 'w') as doc:
            doc.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:body><w:p><w:r><w:t>完整段落</w:t></w:r></w:p></w:body></w:document>')
        result = extract(path.read_bytes(), path.name)
        self.assertEqual(result['text'], '完整段落')
        self.assertTrue(result['warnings'])


if __name__ == '__main__':
    unittest.main()
