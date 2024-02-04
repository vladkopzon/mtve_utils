import sys
import struct


#listing of all formatter to be exported
__all_formatters__ = ['h', 'vh', 'shadow']

def h_formatter(F=None, output=sys.stdout):
    code = []
    max_fields = max(len(section) for section in F.FDB['FUSES'].values())
    max_sections = len(F.FDB['FUSES'])

    code.append('#include <stdio.h>\n')
    code.append(f'#define MAX_FIELDS {max_fields}')
    code.append(f'#define MAX_SECTIONS {max_sections}\n')

    code.append('typedef struct {')
    code.append('    char *key;')
    code.append('    int value;')
    code.append('    int start_pos;')
    code.append('    int stop_pos;')
    code.append('} Field;\n')

    code.append('typedef struct {')
    code.append('    char *sectionName;')
    code.append('    Field fields[MAX_FIELDS];')
    code.append('    int fieldCount;')
    code.append('} Section;\n')

    code.append('void processField(char *sectionName, char *fieldName, int fieldValue, int fieldSize) {')
    code.append('    printf("Section: %s, Field: %s, Value: %d, Size: %d\\n", sectionName, fieldName, fieldValue, fieldSize);')
    code.append('}\n')

    code.append('int main() {')
    code.append('    Section sections[MAX_SECTIONS] = {')
    for section_name, section in F.FDB['FUSES'].items():
        start_pos = F.FDB['__SIZES'][section_name]-1
        code.append('        {')
        code.append(f'            "{section_name}",')
        code.append('            {')

        for field_name, field in section.items():
            stop_pos = start_pos - field["size"]+1
            value = hex(int(field["value"], 2))
            code.append(f'                {{"{field_name}", {value}, {start_pos}, {stop_pos}}},')
            start_pos = stop_pos -1 

        code.append('            },')
        code.append(f'            {len(section)}')
        code.append('        },')

    code.append('    };')
    code.append('    for(int i = 0; i < MAX_SECTIONS; i++) {')
    code.append('        for(int j = 0; j < sections[i].fieldCount; j++) {')
    code.append('            processField(sections[i].sectionName, sections[i].fields[j].key, sections[i].fields[j].value, sections[i].fields[j].start_pos, sections[i].fields[j].stop_pos);')
    code.append('        }')
    code.append('    }')
    code.append('    return 0;')
    code.append('}')

    print('\n'.join(code), file=output)
    return(1)


def vh_formatter(F=None, output=sys.stdout):
    start_pos = F.CFG['__FUSE_BLOCK_SIZE__']-1
    for section, fields in F.FDB['FUSES'].items():
        print("//Section: %s" % section, file=output)
        for fn, f in fields.items():
            stop_pos         = start_pos - f['size']+1
            start_reg        = start_pos//F.CFG['__FUSE_X__']
            start_reg_offset = start_pos%F.CFG['__FUSE_X__']
            stop_reg         = stop_pos//F.CFG['__FUSE_X__']
            stop_reg_offset  = stop_pos%F.CFG['__FUSE_X__']
            if start_reg == stop_reg:
                print(f'`define {section}_{fn}_range [{start_reg}][{start_reg_offset}:{stop_reg_offset}]',
                      file=output)
            elif start_reg - 1 == stop_reg:
                print(f'`define {section}_{fn}_range_high [{start_reg}][{start_reg_offset}:0]',
                      file=output)
                reminded_width = f['size'] - start_reg_offset -1
                #print(start_reg_offset, stop_reg_offset, reminded_width, file=output)
                print(f'`define {section}_{fn}_range_low  [{stop_reg}][{31}:{stop_reg_offset}]',
                      file=output)
            else:
                print(f'//{section}.{fn} is too wide [{f["size"]}], probably SPARE', file=output)
            start_pos = stop_pos -1 
        print("", file=output)
    return 1

def shadow_formatter(F=None, output=sys.stdout):
    #bit vector is BE by default
    print(f'//Shadow ARRAY:', file=output)
    bin_vector = F.get_human_vector()
    for i in range(F.CFG['__FUSE_Y__']):
        idx = i*F.CFG['__FUSE_X__']
        val = bin_vector[idx:idx+F.CFG['__FUSE_X__']]
        widx = F.CFG['__FUSE_Y__'] - i -1
        print("%02d: %s" % (widx, struct.pack('>I', int(val, 2)).hex()), file=output)
    return 1
