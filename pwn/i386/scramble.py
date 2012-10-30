from pwn.util import group, p8, u8, p16, p32, u32, align
import random, pwn.util

def scramble(code, **kwargs):
    return xor_additive_feedback(code, **kwargs)

def __parse_kwargs(kwargs):
    avoid     = kwargs.get('avoid', '')
    unclobber = kwargs.get('unclobber', ['esp'])
    only      = kwargs.get('only', '')
    getpc     = kwargs.get('getpc', None)
    avoid = set(b for b in range(256) if chr(b) in avoid or chr(b) not in only)
    return avoid, unclobber, getpc

# def alpha_mixed(code, **kwargs):
#     avoid, getpc = __parse_kwargs(kwargs)
#     pass

def xor_additive_feedback(code, **kwargs):
    """AKA shikata ga nai"""
    avoid, unclobber, getpc = __parse_kwargs(kwargs)
    def encode(code):
        orig_key = p32(random.randint(0, 1 << 32))
        key = orig_key
        while True:
            encoded = []
            keyblock = key
            okkey = True
            for block in group(code, 4):
                block = ''.join(block)
                oblock = pwn.util.xor(block, keyblock)
                keyblock = p32((u32(block) + u32(keyblock)) % (1 << 32))
                for i in range(4):
                    if oblock[i] in avoid:
                        key = list(key)
                        while True:
                            key[i] = chr((ord(key[i]) + 1) % 0x100)
                            if key[i] == orig_key[i]:
                                return None
                            if xor(key[i], block[i]) not in avoid:
                                break
                        key = ''.join(key)
                        okkey = False
                        break
                if not okkey:
                    break

                encoded.append(oblock)
            if okkey:
                break

        encoded = ''.join(encoded)
        return key, encoded

    def regnum(reg):
        if   reg == 'eax':
            return 0
        elif reg == 'ecx':
            return 1
        elif reg == 'edx':
            return 2
        elif reg == 'ebx':
            return 3
        elif reg == 'ebp':
            return 5
        elif reg == 'esi':
            return 6
        elif reg == 'edi':
            return 7

    def choose(bs):
        bs = filter(lambda block: all(b not in avoid for b in block), bs)
        if bs == []:
            raise Exception('Cannot build decoder under given restrictions')
        return random.choice(bs)
    def mix(blocks):
        random.shuffle(blocks)
        return ''.join(blocks)

    length = align(4, len(code))

    decoder_size = sum([2, # clear_counter
                        2 if length <= 255 else 4, # init_counter
                        5, # init key
                        2 + 4 + 1 if getpc is None else len(getpc),
                        3 + 3 + 3, # loop body
                        2]) # loop inst
    cutoff = length - len(code)

    regs = ['eax', 'edx', 'ebx']
    regs = filter(lambda r: r not in unclobber, regs)
    random.shuffle(regs)
    if len(regs) < 3:
        return None
    counter = regnum('ecx')
    key, bufptr = map(regnum, regs[:2])

    clear_counter = \
        [b + p8(0xc0 + counter + counter * 8) for b in '\x31\x29\x33\x2b']

    if length <= 255:
        init_counter = p8(0xb0 + counter) + p8(length)
    else:
        init_counter = '\x66' + p8(0xb8 + counter) + p16(length)

    init_key = p8(0xb8 + key)

    xor = '\x31' + p8(0x40 + bufptr + 8 * key)
    add = '\x03' + p8(0x40 + bufptr + 8 * key)
    sub4 = '\x83' + p8(0xe8 + bufptr) + p8(-4)
    add4 = '\x83' + p8(0xc0 + bufptr) + p8(4)

    if getpc is None:
        fpu = []
        fpu += ['\xd9' + p8(x) for x in range(0xe8, 0xee)]
        fpu += ['\xd9' + p8(x) for x in range(0xc0, 0xcf)]
        fpu += ['\xd9' + x for x in '\xd0\xe1\xf6\xf7\xe5']
        fpu += ['\xda' + p8(x) for x in range(0xc0, 0xdf)]
        fpu += ['\xdb' + p8(x) for x in range(0xc0, 0xdf)]
        fpu += ['\xdd' + p8(x) for x in range(0xc0, 0xc7)]
        fnstenv = '\xd9\x74\x24\xf4'
        getpc = choose(fpu) + fnstenv + p8(0x58 + bufptr)

    xor1 = xor + p8(decoder_size - cutoff)
    xor2 = xor + p8(decoder_size - 4 - cutoff)
    add1 = add + p8(decoder_size - cutoff)
    add2 = add + p8(decoder_size - 4 - cutoff)

    loop_body = [xor1 + add1 + sub4,
                 xor1 + sub4 + add2,
                 sub4 + xor2 + add2,
                 xor1 + add1 + add4,
                 xor1 + add4 + add2,
                 add4 + xor2 + add2]

    loop_inst = '\xe2\xf5'

    loop = choose(loop_body) + loop_inst

    if cutoff > 0:
        code = loop[-cutoff:] + code
        loop = loop[:-cutoff]

    key, encoded = encode(code)

    init = mix([choose(clear_counter) + init_counter, init_key + key])

    stub = getpc + init + loop

    return stub + encoded