from collections import defaultdict


def read_symvers(filename: str) -> dict[str, tuple[str, str, str]]:
    vers: dict[str, tuple[str, str, str]] = {}
    with open(filename) as f:
        for line in f:
            split = line.strip().split()
            symbol = split[1]
            hash_ = split[0]
            dir_, type_ = split[2], split[3]
            vers[symbol] = (hash_, dir_, type_)
    return vers


def read_lockedlist(filename: str) -> set[str]:
    with open(filename) as f:
        return {line.strip() for line in f if not line.startswith("[")}


def read_lockedlist_grouped(filename: str) -> dict[str, list]:
    module_symbols: defaultdict[str, list] = defaultdict(list)
    with open(filename) as f:
        cur_module = "unknown"
        for line in f:
            line = line.strip()
            if line.startswith("["):
                cur_module = line[1:-1]
            else:
                module_symbols[line].append(cur_module)
    return module_symbols


def read_symbols(filename: str) -> set[str]:
    with open(filename) as f:
        first_line = f.readline()
    if first_line.startswith("["):
        return read_lockedlist(filename)
    else:
        return set(read_symvers(filename).keys())
