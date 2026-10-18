"""Render the authored report subset using only the Python standard library."""
import html
import re


def inline(text):
    saved=[]
    def token(markup):
        saved.append(markup)
        return '@@INLINE'+str(len(saved)-1)+'@@'
    def safe_url(url):
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',url) and not url.startswith(('https://','http://')):return '#'
        if url.startswith('//'):return '#'
        return html.escape(url,quote=True)
    text=re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',lambda m:token('<img src="'+safe_url(m[2])+'" alt="'+html.escape(m[1],quote=True)+'">'),text)
    text=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',lambda m:token('<a href="'+safe_url(m[2])+'">'+html.escape(m[1])+'</a>'),text)
    text=re.sub(r'`([^`]+)`',lambda m:token('<code>'+html.escape(m[1])+'</code>'),text)
    def auto(m):
        url=m[0].rstrip('.,;')
        return token('<a href="'+safe_url(url)+'">'+html.escape(url)+'</a>')+m[0][len(url):]
    text=re.sub(r'https?://[^\s<>]+',auto,text)
    text=html.escape(text)
    text=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)
    for i,markup in enumerate(saved):text=text.replace('@@INLINE'+str(i)+'@@',markup)
    return text


def render(text):
    lines=text.splitlines();out=[];i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('```'):
            code=[];i+=1
            while i<len(lines) and not lines[i].strip().startswith('```'):code.append(lines[i]);i+=1
            out.append('<pre><code>'+html.escape(chr(10).join(code))+'</code></pre>');i+=1;continue
        heading=re.match(r'^(#{1,6})\s+(.*)',line)
        if heading:
            level=len(heading[1]);out.append('<h'+str(level)+'>'+inline(heading[2])+'</h'+str(level)+'>');i+=1;continue
        if line.startswith('|') and i+1<len(lines) and re.match(r'^\|[\s:|+-]+\|$',lines[i+1].strip()):
            cells=lambda s:[x.strip() for x in s.strip().strip('|').split('|')]
            out.append('<div class="scroll"><table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in cells(line))+'</tr></thead><tbody>');i+=2
            while i<len(lines) and lines[i].strip().startswith('|'):
                out.append('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in cells(lines[i]))+'</tr>');i+=1
            out.append('</tbody></table></div>');continue
        bullet=re.match(r'^(?:[-*]|\d+\.)\s+(.*)',line)
        if bullet:
            ordered=bool(re.match(r'^\d+\.',line));tag='ol' if ordered else 'ul';out.append('<'+tag+'>')
            while i<len(lines):
                item=re.match(r'^(?:[-*]|\d+\.)\s+(.*)',lines[i].strip())
                if not item:break
                out.append('<li>'+inline(item[1])+'</li>');i+=1
            out.append('</'+tag+'>');continue
        paragraph=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(?:#{1,6}\s|\||```|[-*]\s|\d+\.\s)',lines[i].strip()):paragraph.append(lines[i].strip());i+=1
        out.append('<p>'+inline(' '.join(paragraph))+'</p>')
    return chr(10).join(out)

