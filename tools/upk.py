# Minimal UE3 package (DUST 514 PS3, ver 708/35) header reader: names, imports, exports.
import struct, json, sys
class Pkg(object):
    def __init__(self, path):
        f = self.f = open(path, 'rb').read()
        o = 4
        self.ver, self.hdr = struct.unpack_from('>II', f, o); o += 8
        n = struct.unpack_from('>i', f, o)[0]; o += 4; o += (-2 * n if n < 0 else n)
        self.flags, nc, no, ec, eo, ic, io = struct.unpack_from('>7I', f, o)
        self.names = []
        o = no
        for i in range(nc):
            n = struct.unpack_from('>i', f, o)[0]; o += 4
            if n < 0: s = f[o:o - 2 * n].decode('utf-16-be', 'replace'); o += -2 * n
            else: s = f[o:o + n].decode('latin1'); o += n
            o += 8; self.names.append(s.rstrip('\x00'))
        self.imports = []
        o = io
        for i in range(ic):
            cp, cpn, cn, cnn, outer, on, onn = struct.unpack_from('>iiiiiii', f, o); o += 28
            self.imports.append((self.names[cp], self.names[cn], outer, self.name(on, onn)))
        self.exports = []
        o = eo
        for i in range(ec):
            cls, sup, outer, on, onn, arch = struct.unpack_from('>iiiiii', f, o); o += 24
            oflags = struct.unpack_from('>Q', f, o)[0]; o += 8
            size, off = struct.unpack_from('>ii', f, o); o += 8
            eflags = struct.unpack_from('>I', f, o)[0]; o += 4
            ngen = struct.unpack_from('>i', f, o)[0]; o += 4 + ngen * 4
            o += 16 + 4  # package guid, package flags
            self.exports.append(dict(cls=cls, sup=sup, outer=outer, name=self.name(on, onn), size=size, off=off, oflags=oflags))
    def name(self, i, n=0):
        s = self.names[i] if 0 <= i < len(self.names) else '?%d' % i
        return s if n == 0 else '%s_%d' % (s, n - 1)
    def objname(self, idx):
        if idx > 0: return self.exports[idx - 1]['name']
        if idx < 0: return self.imports[-idx - 1][3]
        return 'None'
    def path(self, idx):
        parts = []
        while idx:
            parts.append(self.objname(idx))
            idx = self.exports[idx - 1]['outer'] if idx > 0 else self.imports[-idx - 1][2]
        return '.'.join(reversed(parts))
if __name__ == '__main__':
    p = Pkg(sys.argv[1])
    print(len(p.names), len(p.imports), len(p.exports))
    for i, e in enumerate(p.exports[:15]):
        print(i + 1, p.objname(e['cls']), p.path(i + 1), e['size'], hex(e['off']))
