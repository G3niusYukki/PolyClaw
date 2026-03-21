import argparse
import json

from polyclaw.db import Base, SessionLocal, engine
from polyclaw.services.runner import RunnerService


def main() -> None:
    parser = argparse.ArgumentParser(description='PolyClaw runner')
    parser.add_argument('command', choices=['tick'])
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if args.command == 'tick':
            result = RunnerService().tick(session)
            print(json.dumps(result, indent=2, default=str))
    finally:
        session.close()


if __name__ == '__main__':
    main()
