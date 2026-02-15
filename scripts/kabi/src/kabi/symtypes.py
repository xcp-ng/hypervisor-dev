import collections
import zlib

from .utils import pretty


class SymTypes:
    PREFIXES = {
        "t": "",
        "E": "",
        "e": "enum ",
        "s": "struct ",
        "u": "union ",
    }

    def __init__(self):
        self.symtok = {}
        self.symcrc = {}
        self.dupes = collections.defaultdict(set)
        self.file_symvers = collections.defaultdict(dict)
        self.exports = {}

    @classmethod
    def from_file(cls, filename):
        with open(filename) as fp:
            t = cls()
            t.add_file(fp, filename)
            return t

    def name(self, tok):
        if len(tok) >= 2 and tok[1] == "#":
            tok = self.PREFIXES[tok[0]] + tok[2:]
        if "@" in tok:
            tok = tok[: tok.index("@")]
        return tok

    def versioned(self, symbol, filename):
        if symbol in self.dupes:
            crc = self.file_symvers[filename][symbol]
            return f"{symbol}@{crc:08x}"
        return symbol

    def _gen(self, tok, seen, out, filename):
        if tok in seen:
            out.append(self.name(tok))
            return
        seen.add(tok)
        tok = self.versioned(tok, filename)
        for decl_tok in self.symtok[tok]:
            if "#" in decl_tok:
                self._gen(decl_tok, seen, out, filename)
            elif decl_tok != "extern":
                out.append(decl_tok)

    def gen(self, token, filename):
        seen = set()
        tokens = []
        self._gen(token, seen, tokens, filename)
        tokens.append("")
        return " ".join(tokens)

    def gen_short_decl(self, token):
        result = []
        for tok in self.symtok[token]:
            result.append(self.name(tok))
        return pretty(" ".join(result))

    def crc(self, token, fn=None):
        if not fn:
            fn = self.exports[token]
        return zlib.crc32(self.gen(token, fn).encode()) & 0xFFFFFFFF

    def _add_duplicate(self, symbol, crc):
        new_name = f"{symbol}@{crc:08x}"
        self.dupes[symbol].add(new_name)
        return new_name

    def _new_duplicate(self, symbol, crc):
        new_name = f"{symbol}@{self.symcrc[symbol]:08x}"
        self.dupes[symbol].add(new_name)
        self.symtok[new_name] = self.symtok[symbol]
        self.symcrc[new_name] = self.symcrc[symbol]
        del self.symtok[symbol]
        del self.symcrc[symbol]
        return self._add_duplicate(symbol, crc)

    def resolve_duplicate(self, symbol, crc):
        if "@" in symbol:
            orig, crc = symbol.split("@", 1)
            self.dupes[orig].add(symbol)
            return orig, symbol, int(crc, 16)
        if symbol not in self.dupes:
            if symbol not in self.symcrc or self.symcrc[symbol] == crc:
                return symbol, symbol, crc
            else:
                return symbol, self._new_duplicate(symbol, crc), crc
        for potential_symbol in self.dupes[symbol]:
            if self.symcrc[potential_symbol] == crc:
                return symbol, potential_symbol, crc
        return symbol, self._add_duplicate(symbol, crc), crc

    def add(self, symbol_line, filename):
        symbol_line = symbol_line.strip()
        line_crc = zlib.crc32(symbol_line.encode()) & 0xFFFFFFFF
        arr = symbol_line.split()
        token_name = arr[0]
        tokens = arr[1:]

        if token_name.startswith("F#"):
            arc_filename = token_name[2:]
            for tok in tokens:
                if "@" in tok:
                    tok, crc = tok.split("@")
                    crc = int(crc, 16)
                    self.file_symvers[arc_filename][tok] = crc
                else:
                    self.exports[tok] = arc_filename
            if filename in self.file_symvers:
                del self.file_symvers[filename]
            return

        orig, token_name, line_crc = self.resolve_duplicate(token_name, line_crc)

        if filename:
            self.file_symvers[filename][orig] = line_crc

        if token_name in self.symcrc:
            return
        self.symcrc[token_name] = line_crc
        if "#" not in token_name and filename:
            self.exports[token_name] = filename
        self.symtok[token_name] = tokens

    def add_file(self, fileobj, filename):
        for line in fileobj:
            self.add(line.strip(), filename)

    def consolidate_symvers(self):
        for filename, symvers_map in self.file_symvers.items():
            for symbol in list(symvers_map.keys()):
                if symbol not in self.dupes:
                    del symvers_map[symbol]

    def filter_exports(self, symbols, verbose=True):
        files_prev = set(self.exports.values())
        for symbol in list(self.exports.keys()):
            if symbol not in symbols:
                del self.exports[symbol]
        files_to_remove = files_prev - set(self.exports.values())
        for fn in files_to_remove:
            if fn in self.file_symvers:
                del self.file_symvers[fn]

        seen_symbols = set()
        queue = collections.deque(self.exports.keys())
        while queue:
            symbol = queue.popleft()
            seen_symbols.add(symbol)
            if symbol in self.dupes:
                queue.extend(self.dupes[symbol])
            else:
                for dep in self.deps(symbol):
                    if dep not in seen_symbols:
                        queue.append(dep)
        symbols_to_remove = set(self.symtok.keys()) - seen_symbols
        for symbol in symbols_to_remove:
            del self.symtok[symbol]
            del self.symcrc[symbol]

        if verbose:
            rmvd = len(files_to_remove)
            curr = len(self.file_symvers)
            orig = rmvd + curr
            print(f"Reduced files from {orig} to {curr}, a {100 * rmvd / orig:2.1f}% reduction.")
            rmvd = len(symbols_to_remove)
            curr = len(self.symtok)
            orig = rmvd + curr
            print(f"Reduced symbols from {orig} to {curr}. A {100 * rmvd / orig:2.1f}% reduction.")

    def write(self, fp):
        for symbol, tokens in sorted(self.symtok.items()):
            fp.write(f"{symbol} {' '.join(tokens)}\n")
        files = set(self.exports.values()) | set(self.file_symvers.keys())
        filename_to_symbols = collections.defaultdict(list)
        for sym, fn in self.exports.items():
            filename_to_symbols[fn].append(sym)
        for filename in sorted(files):
            outline = []
            outline.extend(filename_to_symbols.get(filename, []))
            outline.extend([f"{s}@{v:08x}" for s, v in self.file_symvers[filename].items()])
            outline.sort()
            fp.write(f"F#{filename} {' '.join(outline)}\n")

    def deps(self, symbol):
        deps = set()
        for tok in self.symtok[symbol]:
            if "#" not in tok:
                continue
            deps.add(tok)
        return deps

    @staticmethod
    def identify_kabi_difference(st1, st2, symbol):
        queue = collections.deque()
        queue.append(symbol)
        changed_symbols = set()
        seen = set()
        fn1 = st1.exports[symbol]
        fn2 = st2.exports[symbol]
        while queue:
            symbol = queue.popleft()
            seen.add(symbol)
            vs1 = st1.versioned(symbol, fn1)
            vs2 = st2.versioned(symbol, fn2)
            if st1.symcrc[vs1] != st2.symcrc[vs2]:
                changed_symbols.add((symbol, vs1, vs2))
            for sym in st1.deps(vs1) & st2.deps(vs2):
                if sym not in seen:
                    queue.append(sym)
        return changed_symbols
