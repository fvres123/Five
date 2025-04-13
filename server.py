import socket
import json
import threading
import datetime
import os
import hashlib

class GomokuServer:
    def __init__(self, host='0.0.0.0', port=5000, password='admin123'):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((host, port))
        self.server.listen(2)
        self.clients = []
        self.client_info = {}  # 存储客户端信息，包括颜色选择、用户名等
        self.ready_clients = set()
        self.color_selection = {}  # 存储玩家颜色选择
        self.server_password = password  # 服务器密码
        self.game_state = {
            'board': [[None for _ in range(15)] for _ in range(15)],
            'current_player': 'black',
            'game_over': False,
            'winner': None,
            'game_started': False,
            'ready_players': 0,
            'players': {},  # 存储玩家信息
            'stage': 'waiting_join',  # 游戏阶段: waiting_join, color_selection, waiting_ready, playing, game_over
            'restart_votes': 0  # 重新开始的投票数
        }
        
        # 确保日志目录存在
        self.log_dir = "game_logs"
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        self.current_game_id = None
        print(f"服务器启动在 {host}:{port}")
        print(f"使用密码: {password}")

    def log_game_event(self, event_type, data=None):
        """记录游戏事件到日志文件"""
        if not self.current_game_id:
            return
            
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "game_id": self.current_game_id
        }
        
        if data:
            log_entry.update(data)
            
        log_file = os.path.join(self.log_dir, f"game_{self.current_game_id}.json")
        
        # 写入日志
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"写入日志失败: {e}")

    def verify_password(self, password):
        """验证密码是否正确"""
        return password == self.server_password

    def handle_client(self, client_socket, addr):
        # 初始化客户端信息
        self.client_info[client_socket] = {
            'addr': addr,
            'username': None,
            'color': None,
            'ready': False,
            'authenticated': False  # 新增认证标志
        }
        
        # 发送初始状态 - 要求进行身份验证
        initial_state = {
            'stage': 'authentication',  # 认证阶段
            'message': '请输入服务器密码和您的用户名',
            'client_id': len(self.clients) - 1  # 客户端ID（0或1）
        }
        client_socket.send(json.dumps(initial_state).encode('utf-8'))
        
        while True:
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                message = json.loads(data)
                
                # 处理身份验证
                if message.get('type') == 'authentication':
                    password = message.get('password', '')
                    username = message.get('username', f"玩家{len(self.clients)}")
                    
                    if self.verify_password(password):
                        self.client_info[client_socket]['authenticated'] = True
                        self.client_info[client_socket]['username'] = username
                        self.game_state['players'][username] = {'color': None, 'ready': False}
                        print(f"玩家 {username} 已验证身份并连接")
                        
                        # 发送认证成功消息
                        auth_success = {
                            'stage': 'waiting_join',
                            'auth_success': True,
                            'message': '身份验证成功'
                        }
                        auth_success.update(self.game_state)
                        client_socket.send(json.dumps(auth_success).encode('utf-8'))
                        
                        # 更新游戏状态
                        if len(self.clients) == 2 and all(info['authenticated'] for info in self.client_info.values()):
                            self.game_state['stage'] = 'color_selection'
                            self.broadcast(json.dumps(self.game_state))
                    else:
                        # 认证失败，通知客户端
                        auth_failed = {
                            'stage': 'authentication',
                            'auth_success': False,
                            'message': '密码错误，请重试'
                        }
                        client_socket.send(json.dumps(auth_failed).encode('utf-8'))
                        continue
                
                # 以下消息都需要已通过身份验证
                if not self.client_info[client_socket]['authenticated']:
                    auth_required = {
                        'stage': 'authentication',
                        'auth_success': False,
                        'message': '请先进行身份验证'
                    }
                    client_socket.send(json.dumps(auth_required).encode('utf-8'))
                    continue
                
                # 处理设置用户名 - 现在用户名在认证时已提供
                if message.get('type') == 'set_username':
                    # 更新游戏状态
                    if len(self.clients) == 2 and all(info['authenticated'] for info in self.client_info.values()):
                        self.game_state['stage'] = 'color_selection'
                        self.broadcast(json.dumps(self.game_state))
                
                # 处理颜色选择
                elif message.get('type') == 'select_color':
                    if self.game_state['stage'] == 'color_selection':
                        selected_color = message.get('color')
                        username = self.client_info[client_socket]['username']
                        
                        # 检查颜色是否可用
                        if selected_color in ['black', 'white']:
                            taken_colors = [info['color'] for info in self.client_info.values() if info['color']]
                            if selected_color not in taken_colors:
                                self.client_info[client_socket]['color'] = selected_color
                                self.game_state['players'][username]['color'] = selected_color
                                
                                # 如果所有玩家都选择了颜色
                                if all(info['color'] for info in self.client_info.values()):
                                    self.game_state['stage'] = 'waiting_ready'
                                
                                # 如果只有一个玩家选择了颜色，给另一个玩家分配另一个颜色
                                elif len([info for info in self.client_info.values() if info['color']]) == 1:
                                    other_color = 'white' if selected_color == 'black' else 'black'
                                    for c, info in self.client_info.items():
                                        if c != client_socket and not info['color']:
                                            info['color'] = other_color
                                            self.game_state['players'][info['username']]['color'] = other_color
                                    self.game_state['stage'] = 'waiting_ready'
                                
                                # 为每个客户端发送包含其颜色的游戏状态
                                for client, info in self.client_info.items():
                                    if info['authenticated'] and info['color']:
                                        client_state = self.game_state.copy()
                                        client_state['your_color'] = info['color']
                                        client.send(json.dumps(client_state).encode('utf-8'))
                                    else:
                                        # 对于未选择颜色的客户端，发送当前状态
                                        client.send(json.dumps(self.game_state).encode('utf-8'))
                
                # 处理准备状态
                elif message.get('type') == 'ready':
                    if self.game_state['stage'] == 'waiting_ready':
                        if client_socket not in self.ready_clients:
                            self.ready_clients.add(client_socket)
                            username = self.client_info[client_socket]['username']
                            self.client_info[client_socket]['ready'] = True
                            self.game_state['players'][username]['ready'] = True
                            self.game_state['ready_players'] = len(self.ready_clients)
                            
                            # 当两个玩家都准备好时，开始游戏
                            if len(self.ready_clients) == 2:
                                self.start_new_game()
                            
                            # 广播更新后的游戏状态
                            self.broadcast(json.dumps(self.game_state))
                
                # 处理移动
                elif message.get('type') == 'move' and self.game_state['stage'] == 'playing':
                    row, col = message['row'], message['col']
                    current_player = self.game_state['current_player']
                    client_color = self.client_info[client_socket]['color']
                    
                    print(f"处理移动: 玩家 {self.client_info[client_socket]['username']} ({client_color}) "
                          f"尝试在 ({row},{col}) 放置棋子, 当前回合: {current_player}")
                    
                    # 确保只有当前回合的玩家可以下棋
                    if client_color == current_player:
                        # 确保位置有效且为空
                        if (0 <= row < 15 and 0 <= col < 15 and 
                            self.game_state['board'][row][col] is None and 
                            not self.game_state['game_over']):
                            
                            print(f"有效移动: 在 ({row},{col}) 放置 {current_player} 棋子")
                            
                            # 更新棋盘
                            self.game_state['board'][row][col] = current_player
                            
                            # 记录移动
                            self.log_game_event("move", {
                                "player": self.client_info[client_socket]['username'],
                                "color": current_player,
                                "position": [row, col]
                            })
                            
                            # 检查胜利条件
                            if self.check_win(row, col):
                                self.game_state['game_over'] = True
                                self.game_state['winner'] = current_player
                                self.game_state['stage'] = 'game_over'
                                winner_username = self.client_info[client_socket]['username']
                                
                                # 记录游戏结束
                                self.log_game_event("game_end", {
                                    "winner": winner_username,
                                    "winner_color": current_player
                                })
                            else:
                                self.game_state['current_player'] = 'white' if current_player == 'black' else 'black'
                            
                            # 广播更新后的游戏状态
                            self.broadcast(json.dumps(self.game_state))
                        else:
                            print(f"无效移动: 位置 ({row},{col}) 已被占用或超出边界")
                    else:
                        print(f"越权移动: 当前回合是 {current_player}, 但 {client_color} 尝试移动")
                
                # 处理重新开始投票
                elif message.get('type') == 'restart_vote' and self.game_state['stage'] == 'game_over':
                    self.game_state['restart_votes'] += 1
                    
                    # 如果所有玩家都投票重新开始
                    if self.game_state['restart_votes'] >= len(self.clients):
                        self.reset_game_state()
                        self.ready_clients.clear()
                        self.game_state['stage'] = 'color_selection'
                        
                        # 重置玩家颜色和准备状态
                        for client in self.client_info:
                            self.client_info[client]['ready'] = False
                            self.client_info[client]['color'] = None  # 重置颜色
                            username = self.client_info[client]['username']
                            if username in self.game_state['players']:
                                self.game_state['players'][username]['ready'] = False
                                self.game_state['players'][username]['color'] = None  # 重置颜色
                            
                        # 记录游戏重新开始
                        self.log_game_event("game_restart", {
                            "message": "玩家投票重新开始游戏"
                        })
                        
                        print("玩家投票重新开始游戏，进入颜色选择阶段")
                        
                    # 广播更新后的游戏状态
                    self.broadcast(json.dumps(self.game_state))
                    
            except Exception as e:
                print(f"处理客户端消息出错: {e}")
                break
        
        # 客户端断开连接的处理
        username = self.client_info[client_socket]['username'] if client_socket in self.client_info else "未知"
        print(f"客户端 {username}({addr}) 断开连接")
        
        if client_socket in self.ready_clients:
            self.ready_clients.remove(client_socket)
        if client_socket in self.clients:
            self.clients.remove(client_socket)
        if client_socket in self.client_info:
            del self.client_info[client_socket]
            
        client_socket.close()
        
        # 更新游戏状态
        self.game_state['ready_players'] = len(self.ready_clients)
        if self.game_state['stage'] == 'playing':
            # 如果游戏正在进行，记录对方断开连接
            self.log_game_event("player_disconnect", {
                "player": username
            })
            self.game_state['stage'] = 'waiting_join'
            self.game_state['game_started'] = False
        
        # 更新玩家列表
        self.game_state['players'] = {
            info['username']: {'color': info['color'], 'ready': info['ready']}
            for client, info in self.client_info.items()
            if info['username']
        }
        
        # 重置游戏状态
        if len(self.clients) < 2:
            self.reset_game_state()
            self.game_state['stage'] = 'waiting_join'
        
        # 广播更新后的游戏状态
        self.broadcast(json.dumps(self.game_state))

    def start_new_game(self):
        """开始新游戏"""
        self.game_state['game_started'] = True
        self.game_state['stage'] = 'playing'
        self.game_state['current_player'] = 'black'
        self.game_state['board'] = [[None for _ in range(15)] for _ in range(15)]
        self.game_state['game_over'] = False
        self.game_state['winner'] = None
        self.game_state['restart_votes'] = 0
        
        # 生成游戏ID
        self.current_game_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        
        # 记录游戏开始
        player_info = {}
        for client, info in self.client_info.items():
            player_info[info['username']] = {
                "color": info['color']
            }
        
        self.log_game_event("game_start", {
            "players": player_info
        })
        
        print(f"游戏 {self.current_game_id} 开始!")

    def reset_game_state(self):
        """重置游戏状态"""
        self.game_state['board'] = [[None for _ in range(15)] for _ in range(15)]
        self.game_state['game_over'] = False
        self.game_state['winner'] = None
        self.game_state['game_started'] = False
        self.game_state['restart_votes'] = 0
    
    def check_win(self, row, col):
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        current_player = self.game_state['board'][row][col]
        
        for dx, dy in directions:
            count = 1
            # 正向检查
            for i in range(1, 5):
                new_row, new_col = row + i * dx, col + i * dy
                if not (0 <= new_row < 15 and 0 <= new_col < 15):
                    break
                if self.game_state['board'][new_row][new_col] != current_player:
                    break
                count += 1
            # 反向检查
            for i in range(1, 5):
                new_row, new_col = row - i * dx, col - i * dy
                if not (0 <= new_row < 15 and 0 <= new_col < 15):
                    break
                if self.game_state['board'][new_row][new_col] != current_player:
                    break
                count += 1
            if count >= 5:
                return True
        return False

    def broadcast(self, message):
        for client in self.clients:
            try:
                client.send(message.encode('utf-8'))
            except Exception as e:
                print(f"广播消息给客户端出错: {e}")
                if client in self.ready_clients:
                    self.ready_clients.remove(client)
                if client in self.client_info:
                    del self.client_info[client]
                if client in self.clients:
                    self.clients.remove(client)

    def start(self):
        while True:
            try:
                client_socket, addr = self.server.accept()
                print(f"客户端 {addr} 已连接")
                
                # 只接受两个客户端
                if len(self.clients) >= 2:
                    client_socket.send(json.dumps({"error": "服务器已满"}).encode('utf-8'))
                    client_socket.close()
                    print(f"拒绝客户端 {addr} 连接，服务器已满")
                    continue
                
                self.clients.append(client_socket)
                thread = threading.Thread(target=self.handle_client, args=(client_socket, addr))
                thread.daemon = True
                thread.start()
            except Exception as e:
                print(f"接受客户端连接出错: {e}")

if __name__ == '__main__':
    # 从命令行或配置文件读取密码
    import sys
    password = "admin123"  # 默认密码
    
    if len(sys.argv) > 1:
        password = sys.argv[1]
    
    server = GomokuServer(password=password)
    server.start() 