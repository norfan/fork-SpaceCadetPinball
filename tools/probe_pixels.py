import sys
sys.path.insert(0, 'tools')
from analyze_shot import read_bmp

for k in [1, 3, 5, 7]:
    w, h, rows = read_bmp(f'shot_ball{k}.bmp')
    # find ball: scan region for a compact bright blob in lower area
    best = None
    for y in range(560, 700):
        for x in range(150, 400):
            o = x * 4
            r = rows[y][o]; g = rows[y][o+1]; b = rows[y][o+2]
            # chrome ball is bright and bluish-white
            if r > 150 and g > 170 and b > 170:
                best = (x, y)
                break
        if best:
            break
    if not best:
        print(f'ball={k}: not found'); continue
    bx, by = best
    line = []
    for x in range(bx - 24, bx + 25, 4):
        o = x * 4
        line.append(f'({x},{rows[by][o]},{rows[by][o+1]},{rows[by][o+2]})')
    print(f'ball={k} center=({bx},{by})')
    print('   ', ' '.join(line))
