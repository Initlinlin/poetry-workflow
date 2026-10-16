"""Extract user-selected books without OCR or external network calls."""
import io,sys,zipfile,posixpath,re,urllib.parse
from pathlib import Path
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
MAX_TEXT=8_000_000
class PlainHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if self.hidden:return
        if tag in ('h1','h2','h3'):self.parts.append('\n\n'+'#'*int(tag[1])+' ')
        elif tag in ('br','p','div','li','tr','section'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if not self.hidden and tag in ('p','div','h1','h2','h3','section'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
    def text(self):return re.sub(r'\n[ \t]+','\n',''.join(self.parts)).strip()
def archive(data):
    z=zipfile.ZipFile(io.BytesIO(data));items=z.infolist()
    if len(items)>15000 or sum(x.file_size for x in items)>150_000_000 or any(x.file_size>40_000_000 for x in items):raise ValueError('电子书解压后的内容过大，请分卷导入')
    if any(x.flag_bits&1 for x in items):raise ValueError('不支持加密或受保护的电子书')
    return z
def decode(data):
    encodings=('utf-16','utf-8-sig','gb18030') if data[:2] in (b'\xff\xfe',b'\xfe\xff') else ('utf-8-sig','gb18030')
    for coding in encodings:
        try:return data.decode(coding)
        except UnicodeError:pass
    raise ValueError('文件编码无法识别，请另存为 UTF-8 文本')
def extract(data,name):
    suffix=Path(name).suffix.lower();warnings=[];pages=0
    if suffix in ('.txt','.md'):text=decode(data)
    elif suffix=='.epub':
        with archive(data) as z:
            if 'META-INF/encryption.xml' in z.namelist():raise ValueError('电子书含加密内容，请使用未加密版本')
            container=ET.fromstring(z.read('META-INF/container.xml'))
            opf=next((x.attrib.get('full-path') for x in container.iter() if x.tag.endswith('rootfile')),None)
            if not opf:raise ValueError('EPUB 缺少书籍结构信息')
            package=ET.fromstring(z.read(opf));base=posixpath.dirname(opf)
            manifest={x.attrib['id']:x.attrib for x in package.iter() if x.tag.endswith('}item') and 'id' in x.attrib}
            blocks=[];seen=set()
            ordered=[manifest.get(ref.attrib.get('idref'),{}) for ref in package.iter() if ref.tag.endswith('itemref')]
            ordered += [item for item in manifest.values() if item.get('media-type') in ('application/xhtml+xml','text/html')]
            for item in ordered:
                href=urllib.parse.unquote(item.get('href','').split('#')[0]);path=posixpath.normpath(posixpath.join(base,href))
                if path.startswith('../') or path.startswith('/') or not href:raise ValueError('EPUB 章节路径无效')
                if path in seen:continue
                seen.add(path)
                parser=PlainHTML();parser.feed(decode(z.read(path)));t=parser.text()
                if t:blocks.append(t)
            text='\n\n\n'.join(blocks);pages=len(blocks)
            warnings.append('EPUB 包含全部列出的 HTML 正文与附录，可能含目录或重复内容；请核对章节顺序')
    elif suffix=='.docx':
        warnings.append('DOCX 仅提取主文档段落；页眉页脚、脚注、批注、文本框与图片需要另行核对')
        with archive(data) as z:
            doc=ET.fromstring(z.read('word/document.xml'));blocks=[]
            for p in doc.iter():
                if not p.tag.endswith('}p'):continue
                parts=[]
                for node in p.iter():
                    if node.tag.endswith('}t'):parts.append(node.text or '')
                    elif node.tag.endswith('}br'):parts.append('\n')
                    elif node.tag.endswith('}tab'):parts.append('\t')
                textp=''.join(parts)
                style=next((node.attrib.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val','') for node in p.iter() if node.tag.endswith('}pStyle')),'')
                if re.match(r'(?i)(heading|标题)[123]',style):textp='#'*int(style[-1])+' '+textp
                blocks.append(textp)
            text='\n'.join(blocks)
    elif suffix=='.pdf':
        try:from pypdf import PdfReader
        except ImportError:raise ValueError('PDF 提取需要 pypdf；请在当前 Python 环境安装后重试')
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted and reader.decrypt('')==0:raise ValueError('PDF 已加密，请使用未加密文件')
        if len(reader.pages)>2000:raise ValueError('PDF 超过 2000 页，请分卷导入')
        blocks=[]
        for page in reader.pages:
            blocks.append(page.extract_text() or '')
            if sum(len(x) for x in blocks)>MAX_TEXT:raise ValueError('提取文字过多，请分卷导入')
        text='\n\n\n'.join(blocks);pages=len(blocks)
        if not text.strip():raise ValueError('PDF 没有可提取文字，可能是扫描版；请先 OCR 或转为 TXT')
        blank=sum(not x.strip() for x in blocks)
        if blank:warnings.append(f'{blank} 页未提取到文字，可能含图片或扫描页，请核对原书')
        warnings.append('PDF 阅读顺序、页眉页脚与分行可能与原书不同，请在导入预览中核对')
    else:raise ValueError('支持 TXT、Markdown、EPUB、DOCX 与文字版 PDF')
    if len(text)>MAX_TEXT:raise ValueError('提取文字超过 800 万字，请分卷导入')
    if not text.strip():raise ValueError('文件中没有读取到文字')
    return {'text':text,'name':name,'pages':pages,'characters':len(text),'warnings':warnings}
