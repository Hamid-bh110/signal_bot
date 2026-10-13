name: Replay Diagnostic
on:
  workflow_dispatch:
    inputs:
      symbols:
        description: "نمادهای بایننس با کاما"
        default: "SUSDT,BATUSDT,CKBUSDT"
      hours:
        description: "چند ساعت گذشته"
        default: "72"
permissions:
  contents: read
jobs:
  replay:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install requests
      - name: Run replay
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          BALE_BOT_TOKEN: ${{ secrets.BALE_BOT_TOKEN }}
          BALE_CHAT_ID: ${{ secrets.BALE_CHAT_ID }}
          DIAG_SYMBOLS: ${{ inputs.symbols }}
          DIAG_HOURS: ${{ inputs.hours }}
        run: python diag_replay.py