from flask import Flask, request, jsonify
from flask_cors import CORS
import copy
import uuid
from threading import Lock


app = Flask(__name__)
CORS(app)

# Estrutura para salas multiplayer
rooms = {}  # room_id: {"board": ..., "turn": ..., "players": [player1, player2], "winner": ..., "last_move": ..., "created": ...}
room_lock = Lock()

EMPTY = '.'
WHITE = 'w'
BLACK = 'b'
WHITE_KING = 'W'
BLACK_KING = 'B'

# Funções utilitárias para lógica do jogo

def create_board():
    board = []
    for row in range(8):
        board_row = []
        for col in range(8):
            if (row + col) % 2 == 1:
                if row < 3:
                    board_row.append(BLACK)
                elif row > 4:
                    board_row.append(WHITE)
                else:
                    board_row.append(EMPTY)
            else:
                board_row.append(EMPTY)
        board.append(board_row)
    return board

def get_opponent(player):
    return WHITE if player == BLACK else BLACK

def is_king(piece):
    return piece in [WHITE_KING, BLACK_KING]

def get_piece_moves(board, r, c, piece, must_capture=False, path=None, captured=None):
    # path: lista de casas visitadas, captured: lista de capturas feitas
    if path is None:
        path = [(r, c)]
    if captured is None:
        captured = []
    moves = []
    directions = []
    if piece in [WHITE, WHITE_KING]:
        directions.append((-1, -1))
        directions.append((-1, 1))
    if piece in [BLACK, BLACK_KING]:
        directions.append((1, -1))
        directions.append((1, 1))
    if piece in [WHITE_KING, BLACK_KING]:
        # Dama pode ir em todas as casas na diagonal
        for dr, dc in [(-1,-1),(-1,1),(1,-1),(1,1)]:
            # Movimento simples
            step = 1
            while True:
                nr, nc = r + dr*step, c + dc*step
                if 0 <= nr < 8 and 0 <= nc < 8:
                    if board[nr][nc] == EMPTY:
                        if not must_capture:
                            moves.append({'from': (r, c), 'to': (nr, nc), 'capture': None})
                        step += 1
                    elif board[nr][nc].lower() != piece.lower() and board[nr][nc] != EMPTY:
                        # Possível captura à distância
                        step2 = step + 1
                        while True:
                            nr2, nc2 = r + dr*step2, c + dc*step2
                            if 0 <= nr2 < 8 and 0 <= nc2 < 8 and board[nr2][nc2] == EMPTY:
                                if (nr, nc) not in captured:
                                    # Recursivo para múltiplas capturas
                                    new_board = copy.deepcopy(board)
                                    new_board[r][c] = EMPTY
                                    new_board[nr][nc] = EMPTY
                                    new_board[nr2][nc2] = piece
                                    new_captured = captured + [(nr, nc)]
                                    new_path = path + [(nr2, nc2)]
                                    further = get_piece_moves(new_board, nr2, nc2, piece, must_capture=True, path=new_path, captured=new_captured)
                                    if further:
                                        moves.extend(further)
                                    else:
                                        moves.append({'from': path[0], 'to': (nr2, nc2), 'capture': new_captured})
                                step2 += 1
                            else:
                                break
                        break
                    else:
                        break
                else:
                    break
        return moves
    # Peão comum
    for dr, dc in directions:
        nr, nc = r + dr, c + dc
        if 0 <= nr < 8 and 0 <= nc < 8 and board[nr][nc] == EMPTY and not must_capture:
            moves.append({'from': (r, c), 'to': (nr, nc), 'capture': None})
        # Captura
        nr2, nc2 = r + 2*dr, c + 2*dc
        if 0 <= nr2 < 8 and 0 <= nc2 < 8 and board[nr][nc] != EMPTY and board[nr][nc].lower() != piece.lower() and board[nr2][nc2] == EMPTY and (nr, nc) not in captured:
            # Recursivo para múltiplas capturas
            new_board = copy.deepcopy(board)
            new_board[r][c] = EMPTY
            new_board[nr][nc] = EMPTY
            new_board[nr2][nc2] = piece
            new_captured = captured + [(nr, nc)]
            new_path = path + [(nr2, nc2)]
            further = get_piece_moves(new_board, nr2, nc2, piece, must_capture=True, path=new_path, captured=new_captured)
            if further:
                moves.extend(further)
            else:
                moves.append({'from': path[0], 'to': (nr2, nc2), 'capture': new_captured})
    return moves

def valid_moves(board, player):
    moves = []
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if (player == WHITE and piece in [WHITE, WHITE_KING]) or (player == BLACK and piece in [BLACK, BLACK_KING]):
                moves.extend(get_piece_moves(board, r, c, piece))
    # Regra: se houver captura, só pode capturar
    captures = [m for m in moves if m['capture']]
    if captures:
        # Apenas movimentos com o maior número de capturas são válidos
        max_captures = max(len(m['capture']) if isinstance(m['capture'], list) else 1 for m in captures)
        return [m for m in captures if len(m['capture']) == max_captures]
    return moves

def move_piece(board, move):
    sr, sc = move['from']
    er, ec = move['to']
    piece = board[sr][sc]
    board[sr][sc] = EMPTY
    board[er][ec] = piece
    # Promoção
    if piece == WHITE and er == 0:
        board[er][ec] = WHITE_KING
    if piece == BLACK and er == 7:
        board[er][ec] = BLACK_KING
    # Captura
    if move['capture']:
        if isinstance(move['capture'], list):
            for cr, cc in move['capture']:
                board[cr][cc] = EMPTY
        else:
            cr, cc = move['capture']
            board[cr][cc] = EMPTY
    return board

def board_to_dict(board):
    return {'board': board}

# IA simples: escolhe o primeiro movimento válido

def ai_move(board, player):
    moves = valid_moves(board, player)
    if not moves:
        return None, board
    move = moves[0]
    new_board = copy.deepcopy(board)
    move_piece(new_board, move)
    return move, new_board


# --- API multiplayer ---

@app.route('/api/create_room', methods=['POST'])
def create_room():
    with room_lock:
        room_id = str(uuid.uuid4())[:8]
        board = create_board()
        rooms[room_id] = {
            "board": board,
            "turn": WHITE,
            "players": [],
            "winner": None,
            "last_move": None
        }
    return jsonify({"room_id": room_id})

@app.route('/api/join_room', methods=['POST'])
def join_room():
    data = request.json
    room_id = data.get("room_id")
    player = data.get("player")
    with room_lock:
        if room_id not in rooms:
            return jsonify({"error": "Sala não encontrada"}), 404
        if player not in [WHITE, BLACK]:
            return jsonify({"error": "Cor inválida"}), 400
        if player in rooms[room_id]["players"]:
            return jsonify({"error": "Jogador já entrou"}), 400
        if len(rooms[room_id]["players"]) >= 2:
            return jsonify({"error": "Sala cheia"}), 400
        rooms[room_id]["players"].append(player)
    return jsonify({"success": True})

@app.route('/api/game_state', methods=['POST'])
def game_state():
    data = request.json
    room_id = data.get("room_id")
    with room_lock:
        if room_id not in rooms:
            return jsonify({"error": "Sala não encontrada"}), 404
        room = rooms[room_id]
        return jsonify({
            "board": room["board"],
            "turn": room["turn"],
            "winner": room["winner"],
            "last_move": room["last_move"]
        })

@app.route('/api/move_multiplayer', methods=['POST'])
def move_multiplayer():
    data = request.json
    room_id = data.get("room_id")
    move = data.get("move")
    player = data.get("player")
    with room_lock:
        if room_id not in rooms:
            return jsonify({"error": "Sala não encontrada"}), 404
        room = rooms[room_id]
        if room["winner"]:
            return jsonify({"error": "Jogo já finalizado"}), 400
        if player != room["turn"]:
            return jsonify({"error": "Não é sua vez"}), 400
        moves = valid_moves(room["board"], player)
        found = None
        for m in moves:
            if m['from'] == tuple(move['from']) and m['to'] == tuple(move['to']):
                found = m
                break
        if not found:
            return jsonify({'error': 'Movimento inválido'}), 400
        move_piece(room["board"], found)
        room["last_move"] = found
        # Verifica vitória
        opponent = get_opponent(player)
        if not valid_moves(room["board"], opponent):
            room["winner"] = player
            room["turn"] = None
        else:
            room["turn"] = opponent
        return jsonify({"board": room["board"], "turn": room["turn"], "winner": room["winner"]})

@app.route('/api/new_game', methods=['POST'])
def new_game():
    board = create_board()
    return jsonify({'board': board, 'turn': WHITE, 'winner': None})

@app.route('/api/move', methods=['POST'])
def player_move():
    data = request.json
    board = data['board']
    move = data['move']
    player = data['player']
    moves = valid_moves(board, player)
    # Verifica se o movimento é válido
    found = None
    for m in moves:
        if m['from'] == tuple(move['from']) and m['to'] == tuple(move['to']):
            found = m
            break
    if not found:
        return jsonify({'error': 'Movimento inválido'}), 400
    move_piece(board, found)
    # Verifica vitória
    if not valid_moves(board, get_opponent(player)):
        return jsonify({'board': board, 'turn': None, 'winner': player})
    # Movimento da IA
    ai_m, board = ai_move(board, get_opponent(player))
    if ai_m:
        if not valid_moves(board, player):
            return jsonify({'board': board, 'turn': None, 'winner': get_opponent(player)})
        return jsonify({'board': board, 'turn': player, 'winner': None})
    else:
        return jsonify({'board': board, 'turn': None, 'winner': player})


# Servir index.html e arquivos estáticos
from flask import send_from_directory

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
