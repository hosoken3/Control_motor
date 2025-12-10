# Environment Setup with uv / uvを使った環境設定

This guide explains how to set up the Python environment for this project using [uv](https://github.com/astral-sh/uv), an extremely fast Python package installer and resolver.
(このガイドでは、高速なPythonパッケージインストーラー兼リゾルバーである [uv](https://github.com/astral-sh/uv) を使用して、このプロジェクトのPython環境をセットアップする方法を説明します。)

## Prerequisites / 前提条件

Ensure `uv` is installed. / `uv` がインストールされていることを確認してください。

```bash
# MacOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Setup Steps / セットアップ手順

### 1. Create a Virtual Environment / 仮想環境の作成

Run the following command in the project directory to create a virtual environment in a `.venv` folder.
(プロジェクトディレクトリで以下のコマンドを実行し、`.venv` フォルダに仮想環境を作成します。)

```bash
uv venv
```

### 2. Activate the Virtual Environment / 仮想環境の有効化

*   **Windows (PowerShell)**:
    ```powershell
    .venv\Scripts\activate
    ```

*   **Linux / macOS**:
    ```bash
    source .venv/bin/activate
    ```

### 3. Install Dependencies / 依存関係のインストール

Install the required packages from `requirements.txt` using `uv`.
(`uv` を使用して `requirements.txt` から必要なパッケージをインストールします。)

```bash
uv pip install -r requirements.txt
```

## Running the Code / コードの実行

Once the environment is activated and dependencies are installed, you can run the main script.
(環境が有効化され、依存関係がインストールされたら、メインスクリプトを実行できます。)

```bash
python main_robot_control.py
```
