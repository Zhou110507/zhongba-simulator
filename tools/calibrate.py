"""python -m tools.calibrate measurements.json --output fitted.json"""

import argparse
import json
from pathlib import Path

from billiards.calibration import fit_measurements


def main():
    parser=argparse.ArgumentParser(description='从标注来源的独立测量拟合台呢参数，不自动改写默认配置')
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        result=fit_measurements(json.loads(args.input.read_text(encoding='utf-8')))
    except (ValueError,OSError) as error:
        parser.error(str(error))
    content=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        if args.output.resolve()==args.input.resolve():
            parser.error('输出不能覆盖原始测量文件')
        args.output.write_text(content,encoding='utf-8')
    else:
        print(content)


if __name__=='__main__':
    main()
