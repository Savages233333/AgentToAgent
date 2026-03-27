import sys


def main() -> None:
    query = sys.stdin.read().strip()
    if not query:
        print("sql-toolkit: 未收到输入")
        return

    print(f"sql-toolkit 已执行，收到输入: {query}")


if __name__ == "__main__":
    main()
