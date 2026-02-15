def read_symvers(filename):
    vers = {}
    with open(filename) as f:
        for line in f:
            split = line.strip().split()
            symbol = split[1]
            hash_ = split[0]
            dir_, type_ = split[2], split[3]
            vers[symbol] = (hash_, dir_, type_)
    return vers


def read_lockedlist(filename):
    with open(filename) as f:
        return {line.strip() for line in f if not line.startswith("[")}


def read_symbols(filename):
    with open(filename) as f:
        first_line = f.readline()
    if first_line.startswith("["):
        return read_lockedlist(filename)
    else:
        return set(read_symvers(filename).keys())
