"""Fill Postgres from NSE / NSDL / AMFI. The web app only reads the DB."""

from engine import run_update


def main() -> None:
    for event in run_update():
        kind = event.get("type")
        text = event.get("text") or event.get("label") or ""
        if kind == "error":
            print(f"error  {text}")
        elif kind == "done":
            print(
                f"done   skipped={event.get('historical_skipped')} "
                f"updated={event.get('historical_updated')} "
                f"errors={event.get('errors')}"
            )
        elif text:
            print(f"{kind:6} {text}")


if __name__ == "__main__":
    main()
