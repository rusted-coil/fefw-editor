# fefw-editor 仕様書｜ユニットの成長seed表示

対象は [Antiadvocate/fefw-editor v1.4.0](https://github.com/Antiadvocate/fefw-editor/releases/tag/v1.4.0)（`6cc101c`）。選択中のユニットが現在持つ成長seedを、既存の英語UIに読み取り専用で表示する。

## 画面仕様

- `Units → Stats` のレベル・経験値・HPの近くに `Growth seed` を追加する。表示は `0x1234ABCD` のように `0x` ＋ 大文字16進8桁とする。値がゼロなら `0x00000000`。
- ユニット選択、スロット切替、再読み込みに連動させる。未選択または値を取得できない場合は `—` とする。
- 閲覧だけで未保存フラグ・Undo履歴・セーブ内容を変えない。今回の対象は表示のみ。

## 読み取りと実装箇所

1. **データ取得** — `fefw_layer.py` の `_record(f, u)` で、既存の `UnitPool` 走査が返した現在状態のレコードを使う。`u.start` は展開後ペイロード内のレコード先頭。`0 <= u.start` かつ `u.start + 0x16 <= u.end <= len(f.payload)` を確かめ、`f.payload[u.start + 4] == 36` のときだけ `f.u32(u.start + 0x12)` を読む。条件外は `None` とする。形式番号の確認は1バイト単位で行う。
2. **画面への受け渡し** — 同ファイルの `UnitRecord.__slots__` と初期化に `growth_seed`（`int | None`）を加え、`_record` から渡す。`rec.base` は既に `u.start + 10` を指すので、相対位置の基準は必ず `u.start` とする。
3. **表示更新** — `editor.py` の `_build_stats_tab()` でラベルを作り、`show_unit()` で選択中の値を反映し、`_clear_unit_form()` で消去する。ゼロと未取得は `is None` で区別する。編集欄の差分検出・保存処理への追加は不要。

**フィールドの根拠**　形式36では `+0x12` の4バイトが成長用の `random_seed_`、直後の `+0x16` は別の `lottery_seed_`。どちらもリトルエンディアン。ゲーム側の `Unit + 0x1C0` はロード後のメモリ上の位置である。今回の対応形式は、レコード内の位置を公開コードで照合できた36に限る。[エディタのレコード生成](https://github.com/Antiadvocate/fefw-editor/blob/6cc101c9657e37bd346fc1e351adb0fd79f045ea/unit_entries.py#L305-L313)・[ゲーム側の読み込み順](https://github.com/vexcited/fefw/blob/df86399186e0595aafee2c2b53ed131d91b0a60d/src/game/unit.c#L14200-L14230)

## 受け入れ条件

- 形式36のテストレコードで、`+0x12` からの8バイトが `CD AB 34 12 78 56 34 12` のとき、画面に `0x1234ABCD` が出る。
- seedがゼロのユニット、別のseedを持つユニット、未選択の順に切り替え、それぞれゼロ、選択中の値、`—` に更新される。別スロットの同じ人物に切り替えた場合も、そのスロットの値を表示する。
- 未確認の形式ではレベル等の既存表示を維持し、seed欄は `—` とする。seedの読み取りに必要な長さがない場合も、追加した処理で範囲外を読まない。
- 正常なセーブを開いて表示・選択だけを行い、未保存扱いにならず、元ファイルのバイト列が変化しないことを確認する。

実装の参照先は [UnitRecord と変換処理](https://github.com/Antiadvocate/fefw-editor/blob/6cc101c9657e37bd346fc1e351adb0fd79f045ea/fefw_layer.py#L43-L96)、[Statsタブ](https://github.com/Antiadvocate/fefw-editor/blob/6cc101c9657e37bd346fc1e351adb0fd79f045ea/editor.py#L1035-L1067)、[選択・解除時の更新](https://github.com/Antiadvocate/fefw-editor/blob/6cc101c9657e37bd346fc1e351adb0fd79f045ea/editor.py#L2139-L2195)。
