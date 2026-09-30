"""Tiny Dean Edwards style packer used to build realistic kwik-like fixtures."""

import re

from animepahe_dl.kwik import _encode


def pack(source: str, radix: int = 62) -> str:
    words: list[str] = []
    for word in re.findall(r"\b\w+\b", source):
        if word not in words:
            words.append(word)
    mapping = {w: _encode(i, radix) for i, w in enumerate(words)}
    keywords = [w if mapping[w] != w else "" for w in words]
    payload = re.sub(r"\b\w+\b", lambda m: mapping[m.group(0)], source)
    payload = payload.replace("\\", "\\\\").replace("'", "\\'")
    return (
        "eval(function(p,a,c,k,e,d){e=function(c){return(c<a?'':e(parseInt(c/a)))+((c=c%a)>35?"
        "String.fromCharCode(c+29):c.toString(36))};if(!''.replace(/^/,String)){while(c--){d[e(c)]=k[c]||e(c)}"
        "k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};while(c--){if(k[c]){p=p.replace("
        "new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}return p}"
        f"('{payload}',{radix},{len(words)},'{'|'.join(keywords)}'.split('|'),0,{{}}))"
    )
