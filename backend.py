from flask import Flask, request, jsonify
from flask_cors import CORS
import copy
import uuid
from threading import Lock
import time

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
            step = 1
            while True:
                nr, nc = r + dr*step, c + dc*step
                if 0 <= nr < 8 and 0 <= nc < 8:
                    if board[nr][nc] == EMPTY:
                        if not must_capture:
                            moves.append({'from': (r, c), 'to': (nr, nc), 'capture': None})
                        step += 1
                    elif board[nr][nc].lower() != piece.lower() and board[nr][nc] != EMPTY:
                        step2 = step + 1
                        while True:
                            nr2, nc2 = r + dr*step2, c + dc*step2
                            if 0 <= nr2 < 8 and 0 <= nc2 < 8 and board[nr2][nc2] == EMPTY:
                                if (nr, nc) not in captured:
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
            "last_move": None,
            "created": time.time()
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
        
        room = rooms[room_id]
        
        # Verifica se o jogador já está na sala
        if player in room["players"]:
            return jsonify({"error": "Jogador já entrou"}), 400
        
        # Verifica se a sala está cheia
        if len(room["players"]) >= 2:
            return jsonify({"error": "Sala cheia"}), 400
        
        # Adiciona o jogador à sala
        room["players"].append(player)
        
        # Se for o segundo jogador, inicia o jogo
        if len(room["players"]) == 2:
            room["turn"] = WHITE  # As brancas começam
        
    return jsonify({"success": True, "board": room["board"], "turn": room["turn"]})

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
    move_data = data.get("move")
    player = data.get("player")
    
    with room_lock:
        if room_id not in rooms:
            return jsonify({"error": "Sala não encontrada"}), 404
        
        room = rooms[room_id]
        
        if room["winner"]:
            return jsonify({"error": "Jogo já finalizado"}), 400
        
        if player != room["turn"]:
            return jsonify({"error": "Não é sua vez"}), 400
        
        # Converte as coordenadas para inteiros
        from_row, from_col = move_data['from']
        to_row, to_col = move_data['to']
        move_data['from'] = (int(from_row), int(from_col))
        move_data['to'] = (int(to_row), int(to_col))
        
        # Encontra o movimento válido correspondente
        moves = valid_moves(room["board"], player)
        found_move = None
        
        for m in moves:
            if (m['from'] == move_data['from'] and 
                m['to'] == move_data['to']):
                found_move = m
                break
        
        if not found_move:
            return jsonify({'error': 'Movimento inválido'}), 400
        
        # Executa o movimento
        move_piece(room["board"], found_move)
        room["last_move"] = found_move
        
        # Verifica vitória
        opponent = get_opponent(player)
        if not valid_moves(room["board"], opponent):
            room["winner"] = player
            room["turn"] = None
        else:
            room["turn"] = opponent
        
        return jsonify({
            "board": room["board"], 
            "turn": room["turn"], 
            "winner": room["winner"]
        })

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