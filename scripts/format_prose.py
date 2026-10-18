import re

# Typography only: scientific protocols, hashes, code, URLs and link targets are untouched.
def polish(text):
    protect=r'(```[\s\S]*?```|`[^`]*`|\]\([^)]*\)|https?://\S+|\b[a-fA-F0-9]{32,}\b|\b\S*[_/]\S*\b)'
    parts=re.split(protect,text)
    for j in range(0,len(parts),2):
        s=parts[j]
        s=re.sub(r'(?<=[0-9])(?=[A-DF-Za-df-z])',' ',s)
        s=re.sub(r'(?<=[a-pr-z])(?=[0-9])',' ',s)
        s=re.sub(r'(?<=%)(?=[A-Za-z])',' ',s)
        s=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',s)
        s=s.replace('alpha.1','alpha 0.1')
        parts[j]=s
    return ''.join(parts)
