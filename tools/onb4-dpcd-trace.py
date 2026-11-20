import re,struct,sys
t=open(sys.argv[1]).read()
def get(k):
    m=re.search(r'"%s" = <([0-9a-f]*)>'%k,t); return bytes.fromhex(m.group(1)) if m else b''
cnt=int(re.search(r'"WhateverXeDPCDCount" = (\d+)',t).group(1))
recs=[]
for k in ("WhateverXeDPCDFirst","WhateverXeDPCDLast"):
    b=get(k)
    for i in range(len(b)//80):
        ns,th,*w=struct.unpack_from("<QQ16I",b,i*80)
        if w[0]: recs.append((w[0],ns,w))
seen=set();out=[]
for n,ns,w in sorted(recs):
    if n in seen: continue
    seen.add(n); out.append((n,ns,w))
print("count",cnt,"records",len(out))
lo,hi=(int(sys.argv[2]),int(sys.argv[3])) if len(sys.argv)>3 else (0,1e9)
for n,ns,w in out:
    if not (lo<=n<=hi): continue
    addr,ln,wr,done,res,dl=w[1:7]
    if not done: continue
    data=struct.pack("<4I",*w[8:12])[:dl].hex(' ')
    print(f"#{n:4} {ns/1e9:9.3f} ddi{w[12]} {'W' if wr else 'R'} {addr:#05x} len{ln:2} res={res:#x} {data}")
