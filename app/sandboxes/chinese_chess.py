"""Chinese Chess (Xiangqi) sandbox for multi-agent collaboration.

Provides a structured board environment where agents play by calling the
``make_move`` tool.  The sandbox validates moves, maintains board state,
and detects checkmate / stalemate.

Board coordinate system:
    Rows 0-9 (top = black side, bottom = red side)
    Cols 0-8 (left to right from red's perspective)

Move notation accepted:
    - Coordinate: "r1c1r2c2" (row-col pairs, e.g. "7109" = row7 col1 → row0 col9)
    - Chinese: "炮二平五", "马8进7", etc.
    - Algebraic: "h2e2" (column letter + row number, chess-like)

Piece notation:
    Red:  K(帅) A(仕) B(相) N(马) R(车) C(炮) P(兵)
    Black: k(将) a(士) b(象) n(马) r(车) c(炮) p(卒)
"""
import logging
import re
from typing import Dict, List, Any, Optional, Tuple

from app.core.tool_manager import ToolDefinition
from app.sandboxes.base import BaseSandbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Piece definitions
# ---------------------------------------------------------------------------

RED = "red"
BLACK = "black"

# Piece type constants
KING = "king"
ADVISOR = "advisor"
BISHOP = "bishop"
KNIGHT = "knight"
ROOK = "rook"
CANNON = "cannon"
PAWN = "pawn"

# Unicode display characters for board rendering
_PIECE_CHAR = {
    (RED, KING): "帅", (RED, ADVISOR): "仕", (RED, BISHOP): "相",
    (RED, KNIGHT): "馬", (RED, ROOK): "車", (RED, CANNON): "炮",
    (RED, PAWN): "兵",
    (BLACK, KING): "将", (BLACK, ADVISOR): "士", (BLACK, BISHOP): "象",
    (BLACK, KNIGHT): "马", (BLACK, ROOK): "车", (BLACK, CANNON): "炮",
    (BLACK, PAWN): "卒",
}

# Single-letter codes for internal representation
_PIECE_CODE = {
    (RED, KING): "K", (RED, ADVISOR): "A", (RED, BISHOP): "B",
    (RED, KNIGHT): "N", (RED, ROOK): "R", (RED, CANNON): "C",
    (RED, PAWN): "P",
    (BLACK, KING): "k", (BLACK, ADVISOR): "a", (BLACK, BISHOP): "b",
    (BLACK, KNIGHT): "n", (BLACK, ROOK): "r", (BLACK, CANNON): "c",
    (BLACK, PAWN): "p",
}

_CODE_TO_PIECE = {v: k for k, v in _PIECE_CODE.items()}

# Column letters for algebraic notation (red perspective: a=col0, i=col8)
_COL_LETTERS = "abcdefghi"

# ---------------------------------------------------------------------------
# Initial board setup
# ---------------------------------------------------------------------------

_INITIAL_BOARD = [
    # row 0 (black back rank)
    [("black", ROOK), ("black", KNIGHT), ("black", BISHOP), ("black", ADVISOR),
     ("black", KING), ("black", ADVISOR), ("black", BISHOP), ("black", KNIGHT), ("black", ROOK)],
    # row 1
    [None, None, None, None, None, None, None, None, None],
    # row 2 (black cannons)
    [None, ("black", CANNON), None, None, None, None, None, ("black", CANNON), None],
    # row 3 (black pawns)
    [("black", PAWN), None, ("black", PAWN), None, ("black", PAWN),
     None, ("black", PAWN), None, ("black", PAWN)],
    # row 4 (river)
    [None, None, None, None, None, None, None, None, None],
    # row 5 (river)
    [None, None, None, None, None, None, None, None, None],
    # row 6 (red pawns)
    [("red", PAWN), None, ("red", PAWN), None, ("red", PAWN),
     None, ("red", PAWN), None, ("red", PAWN)],
    # row 7 (red cannons)
    [None, ("red", CANNON), None, None, None, None, None, ("red", CANNON), None],
    # row 8
    [None, None, None, None, None, None, None, None, None],
    # row 9 (red back rank)
    [("red", ROOK), ("red", KNIGHT), ("red", BISHOP), ("red", ADVISOR),
     ("red", KING), ("red", ADVISOR), ("red", BISHOP), ("red", KNIGHT), ("red", ROOK)],
]


def _deep_copy_board(board):
    return [[cell for cell in row] for row in board]


# ---------------------------------------------------------------------------
# Move validation helpers
# ---------------------------------------------------------------------------

def _in_board(r: int, c: int) -> bool:
    return 0 <= r <= 9 and 0 <= c <= 8


def _in_palace(r: int, c: int, color: str) -> bool:
    """Check if position is within the palace (九宫)."""
    if c < 3 or c > 5:
        return False
    if color == RED:
        return 7 <= r <= 9
    return 0 <= r <= 2


def _on_own_side(r: int, c: int, color: str) -> bool:
    """Check if position is on the piece's starting side of the river."""
    if color == RED:
        return r >= 5
    return r <= 4


def _count_between(board, r1: int, c1: int, r2: int, c2: int) -> int:
    """Count pieces strictly between two positions on a line."""
    count = 0
    if r1 == r2:  # horizontal
        lo, hi = min(c1, c2), max(c1, c2)
        for c in range(lo + 1, hi):
            if board[r1][c] is not None:
                count += 1
    elif c1 == c2:  # vertical
        lo, hi = min(r1, r2), max(r1, r2)
        for r in range(lo + 1, hi):
            if board[r][c1] is not None:
                count += 1
    return count


def _is_king_facing(board) -> bool:
    """Check if the two kings face each other on the same column with
    nothing between them (飞将 / 照面)."""
    # Find king positions
    red_king = black_king = None
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p and p[1] == KING:
                if p[0] == RED:
                    red_king = (r, c)
                else:
                    black_king = (r, c)
    if not red_king or not black_king:
        return False
    if red_king[1] != black_king[1]:
        return False
    return _count_between(board, red_king[0], red_king[1],
                          black_king[0], black_king[1]) == 0


def _validate_move(board, fr: int, fc: int, tr: int, tc: int,
                   color: str, piece_type: str) -> Optional[str]:
    """Validate a single move. Returns None if valid, error string otherwise."""
    target = board[tr][tc]
    # Can't capture own piece
    if target and target[0] == color:
        return "不能吃自己的棋子"

    # Piece-specific rules
    dr = tr - fr
    dc = tc - fc

    if piece_type == KING:
        if not _in_palace(tr, tc, color):
            return "将/帅不能离开九宫"
        if abs(dr) + abs(dc) != 1:
            return "将/帅每次只能走一步"

    elif piece_type == ADVISOR:
        if not _in_palace(tr, tc, color):
            return "仕/士不能离开九宫"
        if abs(dr) != 1 or abs(dc) != 1:
            return "仕/士只能斜走一步"

    elif piece_type == BISHOP:
        if not _on_own_side(tr, tc, color):
            return "相/象不能过河"
        if abs(dr) != 2 or abs(dc) != 2:
            return "相/象只能走田字"
        # Check blocking piece (象眼)
        eye_r = fr + dr // 2
        eye_c = fc + dc // 2
        if board[eye_r][eye_c] is not None:
            return "相/象被塞象眼"

    elif piece_type == KNIGHT:
        if not ((abs(dr) == 2 and abs(dc) == 1) or
                (abs(dr) == 1 and abs(dc) == 2)):
            return "马只能走日字"
        # Check blocking piece (蹩马腿)
        if abs(dr) == 2:
            leg_r = fr + (1 if dr > 0 else -1)
            if board[leg_r][fc] is not None:
                return "马被蹩马腿"
        else:
            leg_c = fc + (1 if dc > 0 else -1)
            if board[fr][leg_c] is not None:
                return "马被蹩马腿"

    elif piece_type == ROOK:
        if dr != 0 and dc != 0:
            return "车只能走直线"
        if _count_between(board, fr, fc, tr, tc) != 0:
            return "车路线上有棋子阻挡"

    elif piece_type == CANNON:
        if dr != 0 and dc != 0:
            return "炮只能走直线"
        between = _count_between(board, fr, fc, tr, tc)
        if target is None:
            # Moving without capture: no pieces in between
            if between != 0:
                return "炮移动时路线上不能有棋子"
        else:
            # Capturing: exactly one piece in between (炮架)
            if between != 1:
                return "炮吃子需要恰好一个炮架"

    elif piece_type == PAWN:
        if not _on_own_side(fr, fc, color):
            # Already crossed river: can move forward or sideways
            if color == RED:
                if not (dr == -1 and dc == 0) and not (dr == 0 and abs(dc) == 1):
                    return "过河兵只能前进或横走一步"
            else:
                if not (dr == 1 and dc == 0) and not (dr == 0 and abs(dc) == 1):
                    return "过河卒只能前进或横走一步"
        else:
            # Not crossed river: only forward
            if color == RED:
                if not (dr == -1 and dc == 0):
                    return "兵未过河只能前进"
            else:
                if not (dr == 1 and dc == 0):
                    return "卒未过河只能前进"

    # Simulate the move and check for self-check (including flying general)
    new_board = _deep_copy_board(board)
    new_board[tr][tc] = new_board[fr][fc]
    new_board[fr][fc] = None
    if _is_king_facing(new_board):
        return "走法导致将帅照面"

    if _is_in_check(new_board, color):
        return "走法导致自己被将军"

    return None  # Valid


def _find_king(board, color: str) -> Optional[Tuple[int, int]]:
    """Find king position for a color."""
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p and p[0] == color and p[1] == KING:
                return (r, c)
    return None


def _is_in_check(board, color: str) -> bool:
    """Check if the given color's king is in check."""
    king_pos = _find_king(board, color)
    if king_pos is None:
        return True  # King captured = definitely in check
    kr, kc = king_pos
    opponent = BLACK if color == RED else RED

    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p and p[0] == opponent:
                # Check if this piece can attack the king
                if _can_attack(board, r, c, kr, kc, p[0], p[1]):
                    return True
    return False


def _can_attack(board, fr: int, fc: int, tr: int, tc: int,
                color: str, piece_type: str) -> bool:
    """Check if a piece at (fr,fc) can attack position (tr,tc).
    Simplified — only checks geometry and blocking, not self-check."""
    dr = tr - fr
    dc = tc - fc

    if piece_type == KING:
        return abs(dr) + abs(dc) == 1 and _in_palace(tr, tc, color)

    if piece_type == ADVISOR:
        return abs(dr) == 1 and abs(dc) == 1 and _in_palace(tr, tc, color)

    if piece_type == BISHOP:
        if abs(dr) != 2 or abs(dc) != 2:
            return False
        eye_r = fr + dr // 2
        eye_c = fc + dc // 2
        return board[eye_r][eye_c] is None

    if piece_type == KNIGHT:
        if not ((abs(dr) == 2 and abs(dc) == 1) or
                (abs(dr) == 1 and abs(dc) == 2)):
            return False
        if abs(dr) == 2:
            leg_r = fr + (1 if dr > 0 else -1)
            return board[leg_r][fc] is None
        else:
            leg_c = fc + (1 if dc > 0 else -1)
            return board[fr][leg_c] is None

    if piece_type == ROOK:
        if dr != 0 and dc != 0:
            return False
        return _count_between(board, fr, fc, tr, tc) == 0

    if piece_type == CANNON:
        if dr != 0 and dc != 0:
            return False
        return _count_between(board, fr, fc, tr, tc) == 1

    if piece_type == PAWN:
        if color == RED:
            if not _on_own_side(fr, fc, color):
                return (dr == -1 and dc == 0) or (dr == 0 and abs(dc) == 1)
            return dr == -1 and dc == 0
        else:
            if not _on_own_side(fr, fc, color):
                return (dr == 1 and dc == 0) or (dr == 0 and abs(dc) == 1)
            return dr == 1 and dc == 0

    return False


def _has_legal_move(board, color: str) -> bool:
    """Check if the given color has any legal move."""
    for fr in range(10):
        for fc in range(9):
            p = board[fr][fc]
            if p and p[0] == color:
                for tr in range(10):
                    for tc in range(9):
                        if fr == tr and fc == tc:
                            continue
                        err = _validate_move(board, fr, fc, tr, tc,
                                             p[0], p[1])
                        if err is None:
                            return True
    return False


# ---------------------------------------------------------------------------
# Move notation parsing
# ---------------------------------------------------------------------------

# Chinese number mapping
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_CN_DIGIT = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
             "6": 6, "7": 7, "8": 8, "9": 9}
_NUM_TO_CN = {v: k for k, v in _CN_NUM.items()}


def _parse_algebraic(move: str, color: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse algebraic notation like 'h2e2' or 'b10c8'."""
    m = re.match(r'^([a-i])(\d+)-?([a-i])(\d+)$', move.lower())
    if not m:
        return None
    fc = ord(m.group(1)) - ord('a')
    fr = int(m.group(2))
    tc = ord(m.group(3)) - ord('a')
    tr = int(m.group(4))
    # Convert from display coordinates (1-based rows from bottom for red)
    # to internal coordinates
    if color == RED:
        fr = 10 - fr
        tr = 10 - tr
    else:
        fr = fr - 1
        tr = tr - 1
    if not _in_board(fr, fc) or not _in_board(tr, tc):
        return None
    return (fr, fc, tr, tc)


def _parse_coordinate(move: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse coordinate notation.

    Accepts:
    - "7109" (4-digit: row7,col1 → row0,col9)
    - "7,1,0,9" (comma-separated: row,col,row,col)
    """
    # Try comma-separated first
    m = re.match(r'^(\d)\s*,\s*(\d)\s*,\s*(\d)\s*,\s*(\d)$', move)
    if m:
        fr, fc, tr, tc = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if _in_board(fr, fc) and _in_board(tr, tc):
            return (fr, fc, tr, tc)
        return None
    # Try 4-digit format
    m = re.match(r'^(\d)(\d)(\d)(\d)$', move)
    if not m:
        return None
    fr, fc, tr, tc = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if not _in_board(fr, fc) or not _in_board(tr, tc):
        return None
    return (fr, fc, tr, tc)


def _parse_chinese(move: str, board, color: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse Chinese notation like '炮二平五', '马8进7'.

    General format: <piece><column><direction><target>
    - piece: 棋子名 (车/車/馬/马/炮/仕/士/相/象/兵/卒/帅/将)
    - column: 数字 or 中文数字
    - direction: 进/退/平
    - target: 数字 or 中文数字 (distance for 进/退, column for 平)
    """
    # Normalize
    move = move.strip()

    # Piece name mapping
    piece_names = {
        "车": ROOK, "車": ROOK,
        "马": KNIGHT, "馬": KNIGHT,
        "炮": CANNON,
        "仕": ADVISOR, "士": ADVISOR,
        "相": BISHOP, "象": BISHOP,
        "兵": PAWN, "卒": PAWN,
        "帅": KING, "将": KING,
    }

    # Try to match pattern: <piece><col><dir><target>
    pattern = r'^([车車马馬炮仕士相象兵卒帅将])([一二三四五六七八九1-9])([进退平])([一二三四五六七八九1-9])$'
    m = re.match(pattern, move)
    if not m:
        return None

    piece_char = m.group(1)
    col_str = m.group(2)
    direction = m.group(3)
    target_str = m.group(4)

    piece_type = piece_names.get(piece_char)
    if piece_type is None:
        return None

    # Parse column number
    col_num = _CN_NUM.get(col_str) or _CN_DIGIT.get(col_str)
    target_num = _CN_NUM.get(target_str) or _CN_DIGIT.get(target_str)
    if col_num is None or target_num is None:
        return None

    # Chinese chess columns: red counts from right (1=col8), black counts from left (1=col0)
    if color == RED:
        fc = 9 - col_num
        tc = 9 - target_num
    else:
        fc = col_num - 1
        tc = target_num - 1

    if not (0 <= fc <= 8 and 0 <= tc <= 8):
        return None

    # Find the piece on the board
    candidates = []
    for r in range(10):
        p = board[r][fc]
        if p and p[0] == color and p[1] == piece_type:
            candidates.append(r)

    if not candidates:
        return None

    # Determine row based on direction
    if direction == "平":
        # Move horizontally: same row, new column
        # Pick the candidate — for pieces with duplicates (e.g. two rooks),
        # use 前/后 convention, but for simplicity pick the one that makes a valid move
        for fr in candidates:
            tr = fr  # same row for horizontal move
            if _in_board(tr, tc):
                err = _validate_move(board, fr, fc, tr, tc, color, piece_type)
                if err is None:
                    return (fr, fc, tr, tc)
        return None

    elif direction == "进":
        # Forward: red moves toward row 0, black toward row 9
        if piece_type in (ROOK, CANNON, PAWN, KING):
            # Linear pieces: target_num is distance
            dist = target_num
            if color == RED:
                tr = candidates[0] - dist
            else:
                tr = candidates[0] + dist
            tc_col = fc  # same column for forward move of linear pieces
            for fr in candidates:
                if _in_board(tr, tc_col):
                    err = _validate_move(board, fr, fc, tr, tc_col, color, piece_type)
                    if err is None:
                        return (fr, fc, tr, tc_col)
            # Try with target as column (for cross-column forward)
            return None
        else:
            # Knight, Advisor, Bishop: target_num is destination column
            for fr in candidates:
                if color == RED:
                    # Knight forward: row decreases
                    tr_candidates = [fr - 2, fr - 1]
                else:
                    tr_candidates = [fr + 2, fr + 1]
                for tr in tr_candidates:
                    if _in_board(tr, tc):
                        err = _validate_move(board, fr, fc, tr, tc, color, piece_type)
                        if err is None:
                            return (fr, fc, tr, tc)
            return None

    elif direction == "退":
        # Backward: red moves toward row 9, black toward row 0
        if piece_type in (ROOK, CANNON, PAWN, KING):
            dist = target_num
            if color == RED:
                tr = candidates[0] + dist
            else:
                tr = candidates[0] - dist
            tc_col = fc
            for fr in candidates:
                if _in_board(tr, tc_col):
                    err = _validate_move(board, fr, fc, tr, tc_col, color, piece_type)
                    if err is None:
                        return (fr, fc, tr, tc_col)
            return None
        else:
            for fr in candidates:
                if color == RED:
                    tr_candidates = [fr + 2, fr + 1]
                else:
                    tr_candidates = [fr - 2, fr - 1]
                for tr in tr_candidates:
                    if _in_board(tr, tc):
                        err = _validate_move(board, fr, fc, tr, tc, color, piece_type)
                        if err is None:
                            return (fr, fc, tr, tc)
            return None

    return None


# ---------------------------------------------------------------------------
# ChineseChessSandbox
# ---------------------------------------------------------------------------

class ChineseChessSandbox(BaseSandbox):
    """Chinese Chess (象棋) sandbox.

    Manages the board state, validates moves, and detects game-over.
    Agents interact via the ``make_move`` tool.
    """

    description = "中国象棋沙箱 — 两个智能体对弈中国象棋"

    def __init__(self):
        self.board: List[List[Optional[Tuple[str, str]]]] = _deep_copy_board(_INITIAL_BOARD)
        self.current_turn: str = RED  # Red goes first
        self.move_history: List[Dict[str, Any]] = []
        self._agent_roles: Dict[str, str] = {}  # agent_id → "red"/"black"
        self._role_colors: Dict[str, str] = {}  # indexed_role → "red"/"black"
        self._game_over: bool = False
        self._winner: Optional[str] = None
        self._game_over_reason: str = ""
        self._move_count: int = 0

    def on_task_start(self, agents: List[Dict[str, Any]]) -> None:
        """Map agents to red/black based on participant order."""
        participants = [a for a in agents if a.get("role") != "referee"]
        for i, agent in enumerate(participants):
            color = RED if i == 0 else BLACK
            role_key = agent.get("role", f"participant_{i}")
            self._agent_roles[agent["agent_id"]] = color
            self._role_colors[role_key] = color

    def get_tools_for_agent(self, agent_id: str, role: str) -> List[ToolDefinition]:
        """Only participants get the make_move tool; referee gets none."""
        if role == "referee":
            return []
        color = self._role_colors.get(role) or self._agent_roles.get(agent_id, RED)
        color_cn = "红" if color == RED else "黑"
        return [ToolDefinition(
            name="make_move",
            description=(
                f"走一步棋（你是{color_cn}方）。"
                f"请使用中文走法格式：<棋子名><路数><进/退/平><目标>。"
                f"例如：炮二平五、马二进三、车一进四、兵五进一。"
                f"同一列有两个相同棋子时用前/后区分：前车进一、后炮平五。"
                f"也可用坐标格式：起始行,起始列,目标行,目标列 如 9,7,7,6"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "move": {
                        "type": "string",
                        "description": "走法，如 '炮二平五' 或 '9,7,7,6'"
                    }
                },
                "required": ["move"]
            },
            handler=None,
            source="sandbox",
        )]

    def get_state_view(self, agent_id: str, role: str) -> str:
        """Return board state visible to this agent."""
        if role == "referee":
            return self._render_board_text()

        color = self._role_colors.get(role) or self._agent_roles.get(agent_id, RED)
        color_name = "红方" if color == RED else "黑方"
        turn_name = "红方" if self.current_turn == RED else "黑方"
        is_my_turn = "是" if color == self.current_turn else "否"

        my_pieces = self._list_pieces(color)
        opp_pieces = self._list_pieces(BLACK if color == RED else RED)
        captures = self._list_captures(color)
        history_str = self._format_history()

        parts = [
            f"你是{color_name}。当前轮次：{turn_name}走棋（是否轮到你：{is_my_turn}）。已走{self._move_count}步。",
        ]
        if is_my_turn == "是":
            parts.append(f"可吃的棋子：{captures}")
        parts.append(f"你的棋子：{my_pieces}")
        parts.append(f"对方棋子：{opp_pieces}")
        parts.append(f"走法记录：{history_str}")

        return "\n".join(parts)

    async def handle_action(self, agent_id: str, role: str,
                            action: str, **kwargs) -> Dict[str, Any]:
        """Process a make_move tool call."""
        if self._game_over:
            return {"success": False, "error": "游戏已结束"}

        color = self._role_colors.get(role) or self._agent_roles.get(agent_id)
        if color is None:
            return {"success": False, "error": "未识别的玩家"}

        if color != self.current_turn:
            return {
                "success": False,
                "error": f"当前是{'红方' if self.current_turn == RED else '黑方'}的回合，请等待"
            }

        move_str = kwargs.get("move", action)
        if not move_str:
            return {"success": False, "error": "请提供走法"}

        # Try parsing with different notations
        result = None
        # Try coordinate format first (simplest)
        result = _parse_coordinate(move_str)
        # Try algebraic
        if result is None:
            result = _parse_algebraic(move_str, color)
        # Try Chinese notation
        if result is None:
            result = _parse_chinese(move_str, self.board, color)

        if result is None:
            return {
                "success": False,
                "error": (
                    f"无法解析走法 '{move_str}'。"
                    f"请使用中文格式（如 炮二平五、马二进三、车一进四、前车进一），"
                    f"或坐标格式（如 9,7,7,6 表示从行9列7到行7列6）。"
                    f"注意：路数以你方视角为准，红方从右至左一到九路，黑方从左至右1到9路。"
                )
            }

        fr, fc, tr, tc = result

        # Verify piece exists at source
        piece = self.board[fr][fc]
        if piece is None:
            return {"success": False, "error": f"位置({fr},{fc})没有棋子"}
        if piece[0] != color:
            return {"success": False, "error": f"位置({fr},{fc})的棋子不是你的"}

        # Validate move
        err = _validate_move(self.board, fr, fc, tr, tc, color, piece[1])
        if err:
            return {"success": False, "error": err}

        # Execute move
        captured = self.board[tr][tc]
        self.board[tr][tc] = self.board[fr][fc]
        self.board[fr][fc] = None
        self._move_count += 1

        move_record = {
            "move_num": self._move_count,
            "color": color,
            "piece": piece[1],
            "from": [fr, fc],
            "to": [tr, tc],
            "notation": move_str,
            "captured": captured[1] if captured else None,
        }
        self.move_history.append(move_record)

        # Switch turn
        self.current_turn = BLACK if color == RED else RED

        # Check for game over
        self._check_game_over()

        # Build result
        captured_msg = f"，吃掉对方{_PIECE_CHAR.get(captured, captured[1])}" if captured else ""
        color_cn = "红方" if color == RED else "黑方"
        result_msg = f"{color_cn}{move_str}{captured_msg}"

        if self._game_over:
            winner_cn = "红方" if self._winner == RED else "黑方" if self._winner == BLACK else "平局"
            result_msg += f" — 游戏结束！{winner_cn}获胜（{self._game_over_reason}）"

        return {
            "success": True,
            "message": result_msg,
            "move": move_record,
            "current_turn": self.current_turn,
            "game_over": self._game_over,
            "winner": self._winner,
        }

    def check_termination(self) -> Optional[Dict[str, Any]]:
        """Check if the game has ended."""
        if not self._game_over:
            return None
        return {
            "game_over": True,
            "winner": self._winner,
            "reason": self._game_over_reason,
        }

    async def parse_action_output(self, agent_id: str, role: str,
                            text: str) -> Optional[Dict[str, Any]]:
        """Parse an agent's free-text output and extract a chess move.

        Scans the text for recognizable chess notation patterns:
        - Coordinate: "7109"
        - Algebraic: "h2e2"
        - Chinese: "炮二平五", "马8进7"

        If a move is found, calls handle_action internally.

        Returns:
            Result dict from handle_action, or None if no move found.
        """
        if self._game_over:
            return None

        color = self._role_colors.get(role) or self._agent_roles.get(agent_id)
        if color is None:
            return None

        if color != self.current_turn:
            return None

        move_str = self._extract_move_from_text(text, color)
        if move_str is None:
            return None

        return await self.handle_action(agent_id, role, "make_move", move=move_str)

    def _extract_move_from_text(self, text: str, color: str) -> Optional[str]:
        """Extract a chess move string from free-text output.

        Looks for patterns like:
        - "走 h2e2" / "move h2e2"
        - "7109" (4-digit coordinate)
        - "炮二平五" (Chinese notation)
        - Various wrappers: "我走...", "我下...", "出..."
        """
        # Chinese piece name chars for regex
        piece_chars = "车車马馬炮仕士相象兵卒帅将"

        # Priority 1: Chinese notation with common verbs
        # e.g. "我走炮二平五", "出车1进1", "下马8进7"
        cn_pattern = rf'(?:我[走下出]|走|下|出)?([{piece_chars}][一二三四五六七八九1-9][进退平][一二三四五六七八九1-9])'
        m = re.search(cn_pattern, text)
        if m:
            candidate = m.group(1)
            # Verify it actually parses
            result = (_parse_coordinate(candidate) or
                      _parse_algebraic(candidate, color) or
                      _parse_chinese(candidate, self.board, color))
            if result:
                return candidate

        # Priority 2: Algebraic notation (e.g. h2e2, b10c8)
        alg_pattern = r'(?:我[走下出]|走|下|出|move)?\s*([a-i]\d{1,2}-?[a-i]\d{1,2})'
        m = re.search(alg_pattern, text, re.IGNORECASE)
        if m:
            candidate = m.group(1)
            result = _parse_algebraic(candidate, color)
            if result:
                return candidate

        # Priority 3: 4-digit coordinate (standalone or with wrapper)
        coord_pattern = r'(?:我[走下出]|走|下|出)?\s*(\d{4})'
        m = re.search(coord_pattern, text)
        if m:
            candidate = m.group(1)
            result = _parse_coordinate(candidate)
            if result:
                return candidate

        # Priority 4: Try any 4-char substring that looks like Chinese notation
        # without requiring a verb prefix
        for m in re.finditer(rf'([{piece_chars}][一二三四五六七八九1-9][进退平][一二三四五六七八九1-9])', text):
            candidate = m.group(1)
            result = _parse_chinese(candidate, self.board, color)
            if result:
                return candidate

        return None

    def get_action_hint(self, agent_id: str, role: str) -> Optional[str]:
        """Return action hint for Chinese chess participants."""
        if role == "referee":
            return None
        return "请使用 make_move 工具走棋。可吃的棋子已列出具体走法（如「马三进五」），直接选用即可，无需自行推算坐标。若无吃子机会，根据棋子路数组织走法。"

    def on_task_end(self) -> None:
        pass

    def get_display_state(self) -> Dict[str, Any]:
        """Return rendered HTML for frontend display.

        Returns a dict with ``html`` key containing a self-contained HTML
        fragment (inline styles included) so the frontend can insert it
        without any sandbox-specific rendering code.
        """
        return {"html": self._render_html()}

    def _render_html(self) -> str:
        """Render the chess board as a self-contained HTML fragment."""
        turn_cn = "红方" if self.current_turn == RED else "黑方"
        move_count = self._move_count
        game_over = self._game_over

        # Info bar
        info_parts = [f"{turn_cn}走棋", f"第{move_count}步"]
        if game_over:
            w = "红方" if self._winner == RED else "黑方" if self._winner == BLACK else "平局"
            info_parts.append(f"<b>游戏结束：{w}获胜</b>")
        info_html = " · ".join(info_parts)

        # Board grid
        cells = []
        for r in range(10):
            for c in range(9):
                p = self.board[r][c]
                is_river = r in (4, 5)
                bg = "#e8ca8a" if is_river else "#f0d5a0"
                if p:
                    color_cls = "#c62828" if p[0] == RED else "#1a1a1a"
                    bg_piece = "#fff5f5" if p[0] == RED else "#f5f5f5"
                    char = _PIECE_CHAR.get(p, "?")
                    cells.append(
                        f'<div style="display:flex;align-items:center;justify-content:center;'
                        f'width:36px;height:36px;background:{bg};font-size:18px;">'
                        f'<span style="width:30px;height:30px;border-radius:50%;display:flex;'
                        f'align-items:center;justify-content:center;font-size:15px;font-weight:700;'
                        f'border:2px solid {color_cls};color:{color_cls};background:{bg_piece};">'
                        f'{char}</span></div>'
                    )
                else:
                    cells.append(
                        f'<div style="display:flex;align-items:center;justify-content:center;'
                        f'width:36px;height:36px;background:{bg};"></div>'
                    )

        board_html = (
            f'<div style="display:grid;grid-template-columns:repeat(9,36px);'
            f'grid-template-rows:repeat(10,36px);gap:1px;background:#d4a055;'
            f'border:2px solid #8b6914;border-radius:4px;padding:2px;width:fit-content;">'
            + "".join(cells)
            + "</div>"
        )

        # Move history
        history_html = ""
        if self.move_history:
            moves = []
            for m in self.move_history[-15:]:
                cn = "红" if m["color"] == RED else "黑"
                color_style = "color:#c62828" if m["color"] == RED else "color:#333"
                moves.append(
                    f'<span style="{color_style};margin-right:6px;">'
                    f'{m["move_num"]}.{cn}{m["notation"]}</span>'
                )
            history_html = (
                f'<div style="margin-top:8px;font-size:12px;color:#666;line-height:1.6;">'
                f'<b>走法记录：</b>{"".join(moves)}</div>'
            )

        return (
            f'<div style="margin:12px 0;">'
            f'<div style="font-size:13px;color:#666;margin-bottom:8px;">{info_html}</div>'
            f'{board_html}'
            f'{history_html}'
            f'</div>'
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_label(row: int, color: str) -> str:
        """Convert a row number to a human-readable rank label.

        Uses Chinese chess spatial terminology that the model already
        understands, avoiding meaningless numeric row indices.
        """
        if color == RED:
            # Red starts at bottom (row 9), moves toward row 0
            labels = {
                9: "底线", 8: "底线前", 7: "炮位", 6: "兵线",
                5: "河沿", 4: "过河", 3: "过河深", 2: "深入",
                1: "深入", 0: "对方底线",
            }
        else:
            # Black starts at top (row 0), moves toward row 9
            labels = {
                0: "底线", 1: "底线前", 2: "炮位", 3: "兵线",
                4: "河沿", 5: "过河", 6: "过河深", 7: "深入",
                8: "深入", 9: "对方底线",
            }
        return labels.get(row, f"{row}行")

    def _list_pieces(self, color: str) -> str:
        """List all pieces for a color using Chinese notation format.

        Shows each piece as "<前/后><棋子名><路数>(位置)" — the same format
        used in move notation, with spatial rank label.
        """
        from collections import defaultdict

        # Collect pieces: (piece_type, road, row, col, piece_char)
        pieces: List[Tuple[str, int, int, int, str]] = []
        for r in range(10):
            for c in range(9):
                p = self.board[r][c]
                if p and p[0] == color:
                    road = (9 - c) if color == RED else (c + 1)
                    pieces.append((p[1], road, r, c, _PIECE_CHAR.get(p, "?")))

        # Group by piece type for 前/后 disambiguation
        type_groups: Dict[str, List] = defaultdict(list)
        for pt, road, r, c, char in pieces:
            type_groups[pt].append((road, r, c, char))

        type_order = [ROOK, KNIGHT, CANNON, BISHOP, ADVISOR, KING, PAWN]
        parts = []
        for pt in type_order:
            group = type_groups.get(pt, [])
            if not group:
                continue
            group.sort(key=lambda x: (x[0], x[1]))

            road_rows: Dict[int, List[int]] = defaultdict(list)
            for road, r, c, char in group:
                road_rows[road].append(r)

            for road, r, c, char in group:
                cn_road = _NUM_TO_CN.get(road, str(road))
                if len(road_rows[road]) > 1:
                    sorted_rows = sorted(road_rows[road])
                    if color == RED:
                        prefix = "前" if r == sorted_rows[0] else "后"
                    else:
                        prefix = "前" if r == sorted_rows[-1] else "后"
                else:
                    prefix = ""
                pos = self._row_label(r, color)
                parts.append(f"{prefix}{char}{cn_road}({pos})")

        return " ".join(parts)

    def _format_chinese_move(self, fr: int, fc: int, tr: int, tc: int,
                             color: str) -> str:
        """Format a move in standard Chinese notation like '马三进五'.

        Generates the exact move string that can be passed directly to
        make_move, so the model never needs to compute coordinates.
        """
        piece = self.board[fr][fc]
        if not piece:
            return ""
        piece_type = piece[1]
        piece_char = _PIECE_CHAR.get(piece, "?")
        road = (9 - fc) if color == RED else (fc + 1)
        cn_road = _NUM_TO_CN.get(road, str(road))

        # 前/后 prefix for duplicate pieces on same column
        prefix = ""
        same_col = [r for r in range(10)
                    if self.board[r][fc] and self.board[r][fc][0] == color
                    and self.board[r][fc][1] == piece_type]
        if len(same_col) > 1:
            sorted_rows = sorted(same_col)
            if color == RED:
                prefix = "前" if fr == sorted_rows[0] else "后"
            else:
                prefix = "前" if fr == sorted_rows[-1] else "后"

        dr = tr - fr
        dc = tc - fc

        if dc == 0:
            # Same column — vertical
            forward = (color == RED and dr < 0) or (color == BLACK and dr > 0)
            direction = "进" if forward else "退"
            if piece_type in (ROOK, CANNON, PAWN, KING):
                target_num = _NUM_TO_CN.get(abs(dr), str(abs(dr)))
            else:
                target_road = (9 - tc) if color == RED else (tc + 1)
                target_num = _NUM_TO_CN.get(target_road, str(target_road))
        elif dr == 0:
            # Horizontal
            direction = "平"
            target_road = (9 - tc) if color == RED else (tc + 1)
            target_num = _NUM_TO_CN.get(target_road, str(target_road))
        else:
            # Diagonal / knight jump
            forward = (color == RED and dr < 0) or (color == BLACK and dr > 0)
            direction = "进" if forward else "退"
            target_road = (9 - tc) if color == RED else (tc + 1)
            target_num = _NUM_TO_CN.get(target_road, str(target_road))

        return f"{prefix}{piece_char}{cn_road}{direction}{target_num}"

    def _list_captures(self, color: str) -> str:
        """List capture opportunities with exact move notation.

        Returns a human-readable string like:
        "马三进五(吃炮五), 炮二进七(吃馬二)"
        The move notation before parentheses can be directly used as
        the argument to make_move.
        """
        opponent = BLACK if color == RED else RED
        captures = []

        for fr in range(10):
            for fc in range(9):
                p = self.board[fr][fc]
                if not p or p[0] != color:
                    continue
                piece_type = p[1]

                for tr in range(10):
                    for tc in range(9):
                        target = self.board[tr][tc]
                        if not target or target[0] != opponent:
                            continue
                        err = _validate_move(self.board, fr, fc, tr, tc, color, piece_type)
                        if err is None:
                            move_cn = self._format_chinese_move(fr, fc, tr, tc, color)
                            target_char = _PIECE_CHAR.get(target, "?")
                            target_road = (9 - tc) if color == RED else (tc + 1)
                            target_cn_road = _NUM_TO_CN.get(target_road, str(target_road))
                            captures.append(f"{move_cn}(吃{target_char}{target_cn_road})")

        return ", ".join(captures) if captures else "无"

    def _check_game_over(self) -> None:
        """Check for checkmate / stalemate / king capture."""
        # Check if opponent's king was captured
        opponent = self.current_turn  # Just switched
        moving_color = BLACK if opponent == RED else RED

        if _find_king(self.board, opponent) is None:
            self._game_over = True
            self._winner = moving_color
            self._game_over_reason = "将/帅被吃"
            return

        # Check if current player (who needs to move) is in checkmate
        if _is_in_check(self.board, self.current_turn):
            if not _has_legal_move(self.board, self.current_turn):
                self._game_over = True
                self._winner = moving_color
                color_cn = "红方" if self.current_turn == RED else "黑方"
                self._game_over_reason = f"{color_cn}被将死"
                return

        # Check stalemate (no legal moves but not in check)
        if not _has_legal_move(self.board, self.current_turn):
            self._game_over = True
            self._winner = None
            color_cn = "红方" if self.current_turn == RED else "黑方"
            self._game_over_reason = f"{color_cn}无子可走（困毙）"
            return

    def _render_board_text(self, color: Optional[str] = None) -> str:
        """Render the board as a compact text grid with road number headers.

        No row numbers or border characters — only road numbers so the
        model can directly read off positions without any coordinate
        translation.
        """
        # Build column headers — road numbers from the given color's perspective
        if color == RED:
            headers = [_NUM_TO_CN.get(9 - c, str(9 - c)) for c in range(9)]
        elif color == BLACK:
            headers = [str(c + 1) for c in range(9)]
        else:
            headers = [str(c) for c in range(9)]

        lines = []
        # Header line
        lines.append("  " + " ".join(f" {h} " for h in headers))

        for r in range(10):
            cells = []
            for c in range(9):
                p = self.board[r][c]
                if p is None:
                    cells.append(" · ")
                else:
                    cells.append(f" {_PIECE_CHAR.get(p, '?')} ")
            lines.append("  " + " ".join(cells))

            if r == 4:
                lines.append("  ─────────── 楚河汉界 ───────────")

        return "\n".join(lines)

    def _format_history(self) -> str:
        """Format move history for display."""
        if not self.move_history:
            return "（尚无走法）"
        lines = []
        for m in self.move_history[-30:]:
            color_cn = "红" if m["color"] == RED else "黑"
            captured_str = f" 吃{m['captured']}" if m.get("captured") else ""
            lines.append(f"{m['move_num']}. {color_cn} {m['notation']}{captured_str}")
        return "\n".join(lines)
