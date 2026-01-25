import sys
import logging

from src.retrieval import run_retrieval


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print('Usage: python -m src.main "<query text>"')
        raise SystemExit(2)

    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print('Usage: python -m src.main "<query text>"')
        raise SystemExit(2)

    res = run_retrieval(query=query, k_primary=5, k_secondary=3)

    print("\nINTENT:", res.get("intent"))
    print("\nPRIMARY:")
    for i, t in enumerate(res.get("primary", []), 1):
        print(f"\n[{i}]\n{t}")

    print("\n\nSECONDARY:")
    for i, t in enumerate(res.get("secondary", []), 1):
        print(f"\n[{i}]\n{t}")


if __name__ == "__main__":
    main()