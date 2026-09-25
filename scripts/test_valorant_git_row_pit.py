from src.valorant_git_row_pit import parse_time, row_key

def main():
    assert parse_time("2024-05-06") == "2024-05-06T00:00:00+00:00"
    assert row_key(" A ", "B", "2024-01-01T00:00:00+00:00", "T")[0] == "a"
    print("VALORANT_ROW_PIT_SMOKE=PASS")

if __name__ == "__main__":
    main()
