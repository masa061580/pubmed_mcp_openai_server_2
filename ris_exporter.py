"""
RIS Format Exporter for PubMed Data
Converts PubMed metadata to compact RIS format for EndNote/Zotero/Mendeley import
"""

from typing import List, Dict, Any


class RISExporter:
    """PubMedデータをコンパクトなRIS形式に変換するクラス

    最小限のメタデータのみを出力し、EndNote側でPubMedから
    詳細情報（全著者リスト、アブストラクトなど）を自動取得させる運用を想定
    """

    @staticmethod
    def format_date(year: str) -> str:
        """
        年をRIS形式に変換
        例: "2024" → "2024///"
        """
        if year and year.isdigit():
            return f"{year}///"
        return "////"

    @staticmethod
    def escape_ris_field(text: str) -> str:
        """
        RISフィールド用にテキストをエスケープ
        改行を削除し、不正な文字を処理
        """
        if not text:
            return ""
        # 改行を空白に置換
        text = text.replace('\n', ' ').replace('\r', ' ')
        # 連続する空白を1つに
        text = ' '.join(text.split())
        return text

    @classmethod
    def convert_to_ris(cls, paper: Dict[str, Any]) -> str:
        """
        単一のPubMed論文データをコンパクトなRIS形式に変換

        Args:
            paper: PubMedデータ（fetch_batchの返り値形式）
                {
                    "pmid": "12345678",
                    "title": "Study Title",
                    "journal": "Journal Name",
                    "year": "2024",
                    "authors": ["Author 1", "Author 2"],
                    "doi": "10.1234/example"  # optional
                }

        Returns:
            コンパクトなRIS形式の文字列

        含まれるフィールド:
            - TY: 文献タイプ (JOUR = Journal Article)
            - AU: 第一著者のみ
            - TI: タイトル
            - JO: 雑誌名
            - PY: 出版年
            - DO: DOI (あれば)
            - AN: PMID (EndNote がこれを使って詳細情報を取得)
            - DB: データベース名 (PubMed)
        """
        pmid = paper.get('pmid', '')
        title = cls.escape_ris_field(paper.get('title', ''))
        journal = cls.escape_ris_field(paper.get('journal', ''))
        year = paper.get('year', '')
        authors = paper.get('authors', [])
        doi = paper.get('doi', '')

        ris_lines = [
            "TY  - JOUR",  # Type: Journal Article
        ]

        # 第一著者のみ（EndNoteが残りを補完）
        if authors:
            ris_lines.append(f"AU  - {cls.escape_ris_field(authors[0])}")

        # タイトル
        if title:
            ris_lines.append(f"TI  - {title}")

        # 雑誌名
        if journal:
            ris_lines.append(f"JO  - {journal}")

        # 出版年
        if year:
            ris_lines.append(f"PY  - {cls.format_date(year)}")

        # DOI（あれば）
        if doi:
            ris_lines.append(f"DO  - {doi}")

        # PMID（最重要 - EndNoteがこれを使って詳細情報を取得）
        if pmid:
            ris_lines.append(f"AN  - {pmid}")

        # データベース名
        ris_lines.append("DB  - PubMed")

        # 終了マーカー
        ris_lines.append("ER  - ")
        ris_lines.append("")  # 空行

        return "\n".join(ris_lines)

    @classmethod
    def export_multiple_to_ris(cls, papers: List[Dict[str, Any]]) -> str:
        """
        複数のPubMed論文をRIS形式に一括変換

        Args:
            papers: PubMedデータのリスト

        Returns:
            全論文を含むRIS形式の文字列
        """
        if not papers:
            return ""

        ris_entries = [cls.convert_to_ris(paper) for paper in papers]
        return "\n".join(ris_entries)


# 使用例とテスト
if __name__ == "__main__":
    # テスト用サンプルデータ
    sample_papers = [
        {
            "pmid": "12345678",
            "title": "Example Study on Machine Learning in Medicine",
            "journal": "Nature Medicine",
            "year": "2024",
            "authors": ["Smith, John A.", "Doe, Jane B."],
            "doi": "10.1038/s41591-024-12345"
        },
        {
            "pmid": "87654321",
            "title": "COVID-19 Vaccine Efficacy Study",
            "journal": "The Lancet",
            "year": "2023",
            "authors": ["Johnson, Mary", "Williams, David"]
            # DOI なしのケース
        }
    ]

    # RIS形式に変換
    exporter = RISExporter()
    ris_output = exporter.export_multiple_to_ris(sample_papers)

    print("=== Compact RIS Output ===")
    print(ris_output)
    print("\n✅ Ready for import into EndNote/Zotero/Mendeley")
    print("📝 EndNote will auto-fetch full metadata from PubMed using PMID")
