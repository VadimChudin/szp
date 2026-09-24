"""Декодер сетей FBD/LD из проекта CODESYS V3 (.project — zip-архив).

Использование:
    mkdir proj && cd proj && unzip ../Rodina.project
    python3 codesys_ld_decode.py proj            # все POU с сетями
    python3 codesys_ld_decode.py proj <file>.object

Формат восстановлен по данным проекта Rodina: строки берутся из
__shared_data_storage_string_table__.auxiliary, элементы сетей (переменные,
операторы AND/OR, блоки, катушки S/R, метки ветвей LD) — из *.object.
Результат — текстовое выражение каждой сети в порядке исполнения.
"""
import glob
import os
import re
import sys


def varint(b, p):
    r = 0
    s = 0
    while True:
        c = b[p]
        p += 1
        r |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return r, p


def enc(n):
    o = bytearray()
    while True:
        c = n & 0x7f
        n >>= 7
        if n:
            o.append(c | 0x80)
        else:
            o.append(c)
            return bytes(o)


def load_strings(path):
    b = open(path, 'rb').read()
    cnt, p = varint(b, 0)
    tab = {}
    for i in range(cnt):
        idx, p2 = varint(b, p)
        if idx != i:
            raise ValueError('string table index mismatch at %d' % i)
        ln, p3 = varint(b, p2)
        s = b[p3:p3 + ln]
        # Длина 36 без вида GUID: в пересланной копии GUID заменены словами — ищем начало следующей записи.
        if ln == 36 and not re.fullmatch(rb'[0-9a-fA-F-]{36}', s):
            q = p3 + 4
            nxt = enc(i + 1)
            while q < len(b):
                if b[q:q + len(nxt)] == nxt:
                    try:
                        l2, _ = varint(b, q + len(nxt))
                        if l2 < 100000:
                            break
                    except IndexError:
                        pass
                q += 1
            s = b[p3:q]
            p = q
        else:
            p = p3 + ln
        tab[i] = s.decode('utf-8', 'replace')
    return tab


tab = {}
CD=b'\xcd\x01\xcd\x01\xcd\x01\x99\x01'
def name(v): return tab.get(v,'?%d'%v)
IDENT=re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
def tokenize(b):
    p=0;T=[]
    while p<len(b)-6:
        c=b[p]
        if b[p:p+4]==b'\x9b\x01\x9a\x01':
            n,q=varint(b,p+4); t,q2=varint(b,q)
            if b[q2:q2+8]==CD:
                T.append(('V',p,name(n) if n!=205 else '',b[q2+8]));p=q2+16;continue
        if b[p:p+2]==b'\x9a\x01':
            n,q=varint(b,p+2); t,q2=varint(b,q)
            if b[q2:q2+8]==CD:
                T.append(('O',p,name(n) if n!=205 else None,b[q2+8]));p=q2+16;continue
        if b[p:p+2]==b'\xaa\x01' and b[p+2:p+4]==b'\xcd\x01':
            T.append(('O',p,None,0));p+=4;continue
        if b[p:p+2]==b'\xa0\x01' and b[p+2:p+4]==b'\x9f\x01':
            n,q=varint(b,p+4);T.append(('A',p,n));p=q;continue
        if b[p:p+2]==b'\xa2\x01' and b[p+4:p+6]==b'\0\0':
            l,q=varint(b,p+2)
            if l>0: T.append(('L',p,l));p=q;continue
        if b[p:p+2]==b'\xa4\x01' and b[p+4:p+7]==b'\0\0\0':
            l,q=varint(b,p+2)
            if l>0: T.append(('R',p,l));p=q;continue
        if b[p:p+5]==b'\xa1\x01\x00\x99\x01':
            T.append(('RAIL',p));p+=5;continue
        if 0x80<=c and b[p+1]==1 and 0x97<=c<=0xb5:
            # network header
            if b[p+2:p+7]==b'\0'*5:
                try:
                    cm,q=varint(b,p+7)
                    if b[q:q+4]==b'\xcd\x01\xcd\x01' and b[q+4]==0:
                        T.append(('NET',p,name(cm) if cm!=205 else '',b[q+5]));p=q+6;continue
                except: pass
            try: n,q=varint(b,p+2)
            except: p+=1;continue
            nm=tab.get(n,'')
            if nm and IDENT.fullmatch(nm):
                inst=None
                if b[q:q+2]==b'\x9a\x01':
                    iv,q=varint(b,q+2); inst=name(iv)
                elif b[q:q+2]!=b'\xa3\x01':
                    p+=1;continue
                ms=[x for x in (b.find(b'\x9c\x01',q,q+60),b.find(b'\x9f\x01',q,q+60)) if x>0]
                if ms:
                    m=min(ms)
                    if b[m:m+6]==b'\x9f\x01\x00\x00\x99\x01':
                        T.append(('BOX',p,nm,inst));T.append(('AR',m,b[m+13]));p=m+14;continue
                    T.append(('BOX',p,nm,inst));p=m+2;continue
        if b[p:p+2]==b'\x99\x01' and all(x<2 for x in b[p+2:p+9]) and b[p+10]==0x0f and 0<b[p+9]<40:
            T.append(('AR',p,b[p+9]));p+=10;continue
        p+=1
    return T

def fmtv(nm,fl):
    s=nm
    if fl&1: s='NOT '+s
    if fl&16: s='R_TRIG('+s+')'
    if fl&32: s='F_TRIG('+s+')'
    if fl&~49: s+=f'<fl{fl}>'
    return s
class P:
    def __init__(s,T,B=None): s.T=T;s.i=0;s.B=B
    def peek(s): return s.T[s.i] if s.i<len(s.T) else None
    def nxt(s): t=s.T[s.i]; s.i+=1; return t
    def expr(s):
        t=s.nxt()
        k=t[0]
        if k=='V': return fmtv(t[2],t[3])
        if k=='R': return f'N{t[2]}'
        if k=='RAIL': return 'TRUE'
        if k=='BOX':
            outs=[]
            while s.peek() and s.peek()[0]=='O': outs.append(s.nxt())
            ar=s.nxt()
            if ar[0]!='AR': return f'<?box {t} got {ar}>'
            args=[s.expr() for _ in range(ar[2])]
            nm=t[2]; inst=t[3]
            if inst and nm not in ('TON','TOF','TP','R_TRIG','F_TRIG','BLINK') and s.B is not None:
                last=s.T[s.i-1][1]
                key=b'\x9d\x01'+bytes([ar[2]])+b'\x0e'
                k=s.B.find(key,last)
                if k>0:
                    q=k+4;pins=[]
                    for _ in range(ar[2]):
                        v,q=varint(s.B,q);pins.append(name(v))
                    args=[f'{pn}={a}' for pn,a in zip(pins,args)]
            if nm in('AND','OR') and not outs:
                return '('+f' {nm} '.join(args)+')'
            o=','.join(f'{fmtv(x[2],x[3]) if x[2] else "_"}' for x in outs)
            return f'{inst+"=" if inst else ""}{nm}({", ".join(args)})'+(f'=>[{o}]' if o.strip('_,') else '')
        return f'<?{t}>'
    def stmt(s):
        t=s.peek()
        if t[0]=='L':
            s.nxt(); return f'N{t[2]} := {s.expr()}'
        if t[0]=='A':
            s.nxt(); outs=[s.nxt() for _ in range(t[2])]
            e=s.expr()
            names=[]
            for o in outs:
                f=o[3]; nm=o[2]
                names.append({0:'',1:'NOT ',2:'S ',3:'R '}.get(f,f'<{f}>')+str(nm))
            return ', '.join(names)+' := '+e
        if t[0]=='BOX': return s.expr()
        s.nxt(); return f'<skip {t}>'
def decode(path):
    b=open(path,'rb').read()
    T=tokenize(b)
    out=[]
    i=0
    # split by NET
    idx=[k for k,t in enumerate(T) if t[0]=='NET']
    for j,k in enumerate(idx):
        end=idx[j+1] if j+1<len(idx) else len(T)
        net=T[k]; body=T[k+1:end]
        out.append(f'--- NET "{net[2]}" n={net[3]}')
        p=P(body,b)
        try:
            while p.i<len(body): out.append('   '+p.stmt())
        except Exception as e: out.append(f'   !! {e} at {p.i} {body[p.i-1:p.i+2]}')
    return '\n'.join(out)
if __name__ == '__main__':
    root = sys.argv[1]
    tab.update(load_strings(os.path.join(root, '__shared_data_storage_string_table__.auxiliary')))
    files = [sys.argv[2]] if len(sys.argv) > 2 else sorted(glob.glob(os.path.join(root, '*.object')))
    for f in files:
        out = decode(f)
        if out.strip():
            print('=' * 8, os.path.basename(f))
            print(out)
