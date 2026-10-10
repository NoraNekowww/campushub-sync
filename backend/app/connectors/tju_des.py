"""TJU CAS 登录 DES (Guapo DESCore) 的忠实 Python 移植。

来源: https://sso.tju.edu.cn/cas/comm/js/des.js
用途: 登录表单字段 `rsa` = str_enc(用户名 + 密码 + lt, "1", "2", "3")。
在本地算，密码就不必先发给 learning.twt.edu.cn/enc 去加密。
已用该 /enc 端点的真实输出逐条比对验证（tools/verify_des.py）。
"""

SBOX = [[[14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7], [0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8], [4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0], [15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13]], [[15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10], [3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5], [0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15], [13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9]], [[10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8], [13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1], [13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7], [1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12]], [[7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15], [13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9], [10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4], [3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14]], [[2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9], [14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6], [4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14], [11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3]], [[12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11], [10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8], [9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6], [4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13]], [[4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1], [13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6], [1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2], [6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12]], [[13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7], [1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2], [7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8], [2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11]]]

PBOX = [15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9, 1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24]

FPBOX = [39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24]

PC2 = [13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3, 25, 7, 15, 6, 26, 19, 12, 1, 40, 51, 30, 36, 46, 54, 29, 39, 50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31]

LOOP = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]

_BT4 = {
    "0000": "0", "0001": "1", "0010": "2", "0011": "3",
    "0100": "4", "0101": "5", "0110": "6", "0111": "7",
    "1000": "8", "1001": "9", "1010": "A", "1011": "B",
    "1100": "C", "1101": "D", "1110": "E", "1111": "F",
}


def str_to_bt(s):
    """JS strToBt: 每个字符占 16 位（UTF-16 码元，大端），共 4 字符 = 64 位。"""
    bt = [0] * 64
    n = len(s)
    if n > 4:
        n = 4
    for i in range(n):
        k = ord(s[i])
        for j in range(16):
            pw = 1
            for m in range(15, j, -1):
                pw *= 2
            bt[16 * i + j] = int(k / pw) % 2
    return bt


def bt64_to_hex(bt):
    out = []
    for i in range(16):
        out.append(_BT4["".join(str(bt[i * 4 + j]) for j in range(4))])
    return "".join(out)


def get_key_bytes(key):
    kbs = []
    leng = len(key)
    iterator = leng // 4
    remainder = leng % 4
    for i in range(iterator):
        kbs.append(str_to_bt(key[i * 4:i * 4 + 4]))
    if remainder > 0:
        kbs.append(str_to_bt(key[iterator * 4:leng]))
    return kbs


def init_permute(d):
    ip = [0] * 64
    m, n = 1, 0
    for i in range(4):
        k = 0
        for j in range(7, -1, -1):
            ip[i * 8 + k] = d[j * 8 + m]
            ip[i * 8 + k + 32] = d[j * 8 + n]
            k += 1
        m += 2
        n += 2
    return ip


def expand_permute(r):
    ep = [0] * 48
    for i in range(8):
        ep[i * 6 + 0] = r[31] if i == 0 else r[i * 4 - 1]
        ep[i * 6 + 1] = r[i * 4 + 0]
        ep[i * 6 + 2] = r[i * 4 + 1]
        ep[i * 6 + 3] = r[i * 4 + 2]
        ep[i * 6 + 4] = r[i * 4 + 3]
        ep[i * 6 + 5] = r[0] if i == 7 else r[i * 4 + 4]
    return ep


def xor(a, b):
    return [(a[i] + b[i]) % 2 for i in range(len(a))]


def sbox_permute(eb):
    out = [0] * 32
    for i in range(8):
        row = 2 * eb[i * 6 + 0] + eb[i * 6 + 5]
        col = (2 * 2 * 2 * eb[i * 6 + 1] + 2 * 2 * eb[i * 6 + 2]
               + 2 * eb[i * 6 + 3] + eb[i * 6 + 4])
        binary = bin(SBOX[i][row][col])[2:]
        for j in range(4):
            if len(binary) < 4:
                out[i * 4 + j] = 0
                binary = "0" + binary
            else:
                out[i * 4 + j] = int(binary[j])
    return out


def p_permute(sb):
    return [sb[PBOX[i]] for i in range(32)]


def finally_permute(e):
    return [e[FPBOX[i]] for i in range(64)]


def generate_keys(key_byte):
    key = [0] * 56
    for i in range(7):
        for j in range(8):
            k = 7 - j
            key[i * 8 + j] = key_byte[8 * k + i]
    keys = []
    for i in range(16):
        for _ in range(LOOP[i]):
            tl = key[0]
            tr = key[28]
            for k in range(27):
                key[k] = key[k + 1]
                key[28 + k] = key[29 + k]
            key[27] = tl
            key[55] = tr
        keys.append([key[PC2[x]] for x in range(48)])
    return keys


def enc(data_byte, key_byte):
    keys = generate_keys(key_byte)
    ip = init_permute(data_byte)
    left, right = ip[:32], ip[32:]
    for i in range(16):
        temp_left = left[:]
        left = right[:]
        right = xor(p_permute(sbox_permute(xor(expand_permute(right), keys[i]))), temp_left)
    return finally_permute(right + left)


def str_enc(data, first_key="1", second_key="2", third_key="3"):
    """对应 des.js 的 strEnc(data, firstKey, secondKey, thirdKey)。"""
    fk = get_key_bytes(first_key) if first_key else []
    sk = get_key_bytes(second_key) if second_key else []
    tk = get_key_bytes(third_key) if third_key else []
    leng = len(data)
    if leng == 0:
        return ""
    blocks = []
    if leng < 4:
        blocks.append(str_to_bt(data))
    else:
        iterator = leng // 4
        remainder = leng % 4
        for i in range(iterator):
            blocks.append(str_to_bt(data[i * 4:i * 4 + 4]))
        if remainder > 0:
            blocks.append(str_to_bt(data[iterator * 4:leng]))
    parts = []
    for bt in blocks:
        b = bt
        for kb in fk:
            b = enc(b, kb)
        for kb in sk:
            b = enc(b, kb)
        for kb in tk:
            b = enc(b, kb)
        parts.append(bt64_to_hex(b))
    return "".join(parts)
