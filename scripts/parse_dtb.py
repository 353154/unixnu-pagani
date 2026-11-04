import struct
import sys

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

def parse_fdt_nodes(dtb_path):
    with open(dtb_path, 'rb') as f:
        buf = f.read()
    magic, totalsize, off_struct, off_strings, off_rsvmap, ver = struct.unpack('>6I', buf[:24])
    assert magic == 0xd00dfeed
    strings = buf[off_strings:]
    
    def get_str(off):
        end = strings.find(b'\x00', off)
        return strings[off:end].decode('utf-8', errors='ignore')

    p = off_struct
    node_stack = []
    results = {'reserved': [], 'memory': [], 'gic': [], 'psci': [], 'framebuffer': []}
    
    while p < len(buf):
        tag, = struct.unpack('>I', buf[p:p+4])
        p += 4
        if tag == FDT_BEGIN_NODE:
            end = buf.find(b'\x00', p)
            name = buf[p:end].decode('utf-8', errors='ignore')
            p = (end + 4) & ~3
            node_stack.append(name)
        elif tag == FDT_END_NODE:
            if node_stack:
                node_stack.pop()
        elif tag == FDT_PROP:
            val_len, name_off = struct.unpack('>II', buf[p:p+8])
            p += 8
            prop_name = get_str(name_off)
            prop_val = buf[p:p+val_len]
            p = (p + val_len + 3) & ~3
            
            curr_path = '/' + '/'.join(node_stack)
            node_name = node_stack[-1] if node_stack else ''
            
            if 'reserved-memory' in curr_path and prop_name == 'reg' and val_len >= 16:
                addrs = [hex(x) for x in struct.unpack(f'>{val_len//8}Q', prop_val[:val_len-(val_len%8)])]
                results['reserved'].append((node_name, addrs))
            elif 'memory' in node_name and prop_name == 'reg' and val_len >= 16:
                addrs = [hex(x) for x in struct.unpack(f'>{val_len//8}Q', prop_val[:val_len-(val_len%8)])]
                results['memory'].append((curr_path, addrs))
            elif ('intc' in node_name or 'interrupt-controller' in node_name) and prop_name == 'reg' and val_len >= 16:
                addrs = [hex(x) for x in struct.unpack(f'>{val_len//8}Q', prop_val[:val_len-(val_len%8)])]
                results['gic'].append((curr_path, addrs))
            elif 'psci' in node_name and prop_name == 'compatible':
                results['psci'].append((curr_path, prop_val.decode('utf-8', errors='ignore')))
            elif 'framebuffer' in node_name.lower() or 'display' in node_name.lower():
                if prop_name == 'reg' and val_len >= 16:
                    addrs = [hex(x) for x in struct.unpack(f'>{val_len//8}Q', prop_val[:val_len-(val_len%8)])]
                    results['framebuffer'].append((curr_path, addrs))
        elif tag == FDT_NOP:
            continue
        elif tag == FDT_END:
            break
            
    return results

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '/Users/damon/unixnu-pagani/firmware_dump/dtbs/dtb_05.dtb'
    res = parse_fdt_nodes(path)
    print('=== MEMORY NODES ===')
    for m in res['memory']:
        print(m)
    print('\n=== GIC (INTERRUPT CONTROLLER) ===')
    for g in res['gic']:
        print(g)
    print('\n=== PSCI METHOD ===')
    for p in res['psci']:
        print(p)
    print('\n=== RESERVED MEMORY (CRITICAL FOR XNU BRINGUP) ===')
    for r in res['reserved']:
        print(f'{r[0]}: {r[1]}')
    print('\n=== FRAMEBUFFER / DISPLAY NODES ===')
    for fb in res['framebuffer']:
        print(fb)
