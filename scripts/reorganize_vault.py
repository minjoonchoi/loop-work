#!/usr/bin/env python3
"""Plan, inspect and explicitly apply the readable vault layout."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from loop_work.storage import LoopError
from loop_work.vault_migrate import plan, apply


def main():
    parser=argparse.ArgumentParser(description='원문과 실행 기록을 보존하며 vault 문서 배치를 명시적으로 전환합니다.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan',metavar='OUTPUT_JSON',help='원본을 변경하지 않고 전환 계획과 payload를 작성합니다.')
    mode.add_argument('--apply',metavar='PLAN_JSON',help='검토한 계획의 SHA-256을 확인하고 적용합니다.')
    parser.add_argument('--knowledge-home')
    parser.add_argument('--vault')
    parser.add_argument('--expected-plan-sha256')
    args=parser.parse_args()
    if args.plan:
        if not args.knowledge_home or not args.vault or args.expected_plan_sha256:
            parser.error('--plan requires --knowledge-home and --vault; no apply pin is accepted')
        result=plan(args.knowledge_home,args.vault,args.plan)
    else:
        if not args.expected_plan_sha256 or args.knowledge_home or args.vault:
            parser.error('--apply requires --expected-plan-sha256; source paths come from the pinned plan')
        result=apply(args.apply,args.expected_plan_sha256)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:
        main()
    except (LoopError,OSError,ValueError,KeyError) as exc:
        print('Vault 전환 실패: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
