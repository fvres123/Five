import pygame
import sys
import socket
import json
import threading
import os
import time  # 添加时间模块用于光标闪烁

# 初始化Pygame
pygame.init()

# 游戏常量
BOARD_SIZE = 15  # 15x15的棋盘
GRID_SIZE = 40   # 每个格子的大小
MARGIN = 50      # 边距
PIECE_RADIUS = 18  # 棋子半径

# 计算窗口大小
WINDOW_SIZE = BOARD_SIZE * GRID_SIZE + 2 * MARGIN

# 颜色定义
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BROWN = (205, 133, 63)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
GRAY = (200, 200, 200)

# 创建窗口
screen = pygame.display.set_mode((WINDOW_SIZE, WINDOW_SIZE))
pygame.display.set_caption('五子棋 - 网络对战')

# 启用中文输入法支持
pygame.key.start_text_input()  # 启动文本输入模式

# 尝试加载支持中文的字体
try:
    # 尝试常见的中文字体路径
    font_paths = [
        "./FZLTCHJW.TTF",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        # Windows
        "C:/Windows/Fonts/simhei.ttf",
        # 通用
        "simhei.ttf",
        "simsun.ttc",
        "msyh.ttc",
        # 当前目录
        os.path.join(os.path.dirname(__file__), "simhei.ttf")
    ]
    
    font = None
    small_font = None
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = pygame.font.Font(path, 36)
                small_font = pygame.font.Font(path, 24)
                print(f"使用字体：{path}")
                break
            except:
                pass
    
    if font is None:
        # 如果找不到中文字体，使用默认字体
        font = pygame.font.Font(None, 36)
        small_font = pygame.font.Font(None, 24)
        print("警告：未找到支持中文的字体，界面可能显示乱码")
except Exception as e:
    print(f"加载字体出错：{e}")
    font = pygame.font.Font(None, 36)
    small_font = pygame.font.Font(None, 24)

class GomokuClient:
    def __init__(self, host=None, port=5000):
        self.socket = None
        self.connected = False
        
        self.board = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player = 'black'
        self.game_over = False
        self.winner = None
        self.my_color = None  # 从服务器获取的颜色
        self.selected_color = None  # 选择但未提交的颜色
        self.game_started = False
        self.ready_players = 0
        self.is_ready = False
        self.username = ""  # 用户名
        self.players = {}  # 所有玩家信息
        self.stage = 'server_connection'  # 游戏阶段，初始为连接服务器
        self.input_active = False  # 用户名输入框是否活跃
        self.input_text = ""  # 输入文本
        self.password_input = ""  # 密码输入
        self.server_address = host or "localhost"  # 服务器地址
        self.server_port = port  # 服务器端口
        self.has_voted_restart = False  # 是否已投票重新开始
        self.client_id = -1  # 客户端ID
        self.restart_votes = 0  # 重新开始的投票数
        self.cursor_visible = True  # 光标可见状态
        self.cursor_time = 0  # 光标闪烁计时器
        self.error_message = ""  # 错误消息
        self.input_focus = "server"  # 输入焦点：server/username/password
        
    def connect_to_server(self):
        """连接到服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_address, self.server_port))
            self.connected = True
            print(f"已连接到服务器: {self.server_address}:{self.server_port}")
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self.receive_data)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            return True
        except Exception as e:
            self.error_message = f"无法连接到服务器: {e}"
            print(self.error_message)
            return False
            
    def send_authentication(self):
        """发送身份验证信息"""
        if not self.connected:
            return False
            
        try:
            message = json.dumps({
                'type': 'authentication',
                'username': self.username,
                'password': self.password_input
            })
            self.socket.send(message.encode('utf-8'))
            print(f"发送身份验证: 用户名={self.username}")
            return True
        except Exception as e:
            self.error_message = f"发送身份验证失败: {e}"
            print(self.error_message)
            return False

    def receive_data(self):
        while self.connected:
            try:
                data = self.socket.recv(4096).decode('utf-8')
                if not data:
                    break
                
                game_state = json.loads(data)
                
                # 处理错误消息
                if 'error' in game_state:
                    self.error_message = game_state['error']
                    print(f"服务器错误: {self.error_message}")
                    continue
                
                # 处理身份验证响应
                if 'auth_success' in game_state:
                    if game_state['auth_success']:
                        print("身份验证成功")
                        self.stage = game_state.get('stage', 'waiting_join')
                    else:
                        self.error_message = game_state.get('message', '身份验证失败')
                        print(f"身份验证失败: {self.error_message}")
                        self.stage = 'authentication'
                        continue
                
                # 处理游戏阶段变更
                if 'stage' in game_state:
                    old_stage = self.stage
                    self.stage = game_state['stage']
                    
                    # 如果阶段变为颜色选择，重置相关状态
                    if self.stage == 'color_selection':
                        self.selected_color = None  # 重置颜色选择
                        self.is_ready = False  # 重置准备状态
                        print("进入颜色选择阶段，重置颜色选择状态")
                    
                    print(f"游戏阶段从 {old_stage} 变更为 {self.stage}")
                    
                # 更新游戏状态
                self.board = game_state.get('board', self.board)
                self.current_player = game_state.get('current_player', self.current_player)
                self.game_over = game_state.get('game_over', self.game_over)
                self.winner = game_state.get('winner', self.winner)
                self.game_started = game_state.get('game_started', self.game_started)
                self.ready_players = game_state.get('ready_players', self.ready_players)
                self.players = game_state.get('players', self.players)
                self.restart_votes = game_state.get('restart_votes', 0)
                
                # 获取客户端ID
                if 'client_id' in game_state and self.client_id == -1:
                    self.client_id = game_state['client_id']
                
                # 如果服务器分配了颜色
                if 'your_color' in game_state:
                    self.my_color = game_state['your_color']
                    print(f"服务器分配颜色: {self.my_color}")
                    
                # 重置重新开始投票状态
                if old_stage == 'game_over' and self.stage == 'color_selection':
                    self.has_voted_restart = False
                
            except Exception as e:
                print(f"接收数据错误: {e}")
                break
        
        if self.socket:
            self.socket.close()
        self.connected = False
        self.stage = 'server_connection'
        print("与服务器的连接已断开")

    def send_move(self, row, col):
        """发送移动信号"""
        # 只有在轮到自己的时候才能下棋
        if not self.connected:
            return
            
        if (self.stage == 'playing' and 
            self.current_player == self.my_color and 
            not self.game_over and 
            self.board[row][col] is None):
            try:
                message = json.dumps({
                    'type': 'move',
                    'row': row,
                    'col': col
                })
                self.socket.send(message.encode('utf-8'))
                print(f"发送移动: 行={row}, 列={col}")
            except Exception as e:
                print(f"发送移动失败: {e}")

    def select_color(self, color):
        """选择棋子颜色"""
        if not self.connected:
            return False
            
        if self.stage == 'color_selection' and color in ['black', 'white']:
            try:
                message = json.dumps({
                    'type': 'select_color',
                    'color': color
                })
                self.socket.send(message.encode('utf-8'))
                print(f"发送颜色选择: {color}")
                return True
            except Exception as e:
                self.error_message = f"选择颜色失败: {e}"
                print(self.error_message)
                return False
        return False
        
    def send_ready(self):
        """发送准备信号"""
        if not self.connected:
            return False
            
        if self.stage == 'waiting_ready' and not self.is_ready:
            try:
                message = json.dumps({'type': 'ready'})
                self.socket.send(message.encode('utf-8'))
                self.is_ready = True
                return True
            except Exception as e:
                self.error_message = f"发送准备信号失败: {e}"
                print(self.error_message)
                return False
        return False
        
    def vote_restart(self):
        """投票重新开始游戏"""
        if not self.connected:
            return False
            
        if self.stage == 'game_over' and not self.has_voted_restart:
            try:
                message = json.dumps({
                    'type': 'restart_vote'
                })
                self.socket.send(message.encode('utf-8'))
                self.has_voted_restart = True
                return True
            except Exception as e:
                self.error_message = f"投票重新开始失败: {e}"
                print(self.error_message)
                return False
        return False

    def restart_game(self):
        """投票重新开始游戏"""
        if self.socket:
            restart_msg = {
                "action": "restart_vote",
                "username": self.username
            }
            self.socket.send(json.dumps(restart_msg).encode('utf-8'))
            print(f"{self.username} 投票重新开始游戏")
            
            # 重置本地游戏状态
            self.winner = None
            self.selected_color = None  # 重置颜色选择
            self.is_ready = False  # 重置准备状态

def draw_board():
    """绘制棋盘"""
    screen.fill(BROWN)
    # 绘制网格线
    for i in range(BOARD_SIZE):
        # 横线
        pygame.draw.line(screen, BLACK,
                        (MARGIN, MARGIN + i * GRID_SIZE),
                        (WINDOW_SIZE - MARGIN, MARGIN + i * GRID_SIZE))
        # 竖线
        pygame.draw.line(screen, BLACK,
                        (MARGIN + i * GRID_SIZE, MARGIN),
                        (MARGIN + i * GRID_SIZE, WINDOW_SIZE - MARGIN))
    
    # 添加底部和右侧的闭合线
    pygame.draw.line(screen, BLACK,
                    (MARGIN, WINDOW_SIZE - MARGIN),
                    (WINDOW_SIZE - MARGIN, WINDOW_SIZE - MARGIN))
    pygame.draw.line(screen, BLACK,
                    (WINDOW_SIZE - MARGIN, MARGIN),
                    (WINDOW_SIZE - MARGIN, WINDOW_SIZE - MARGIN))

def draw_pieces(game):
    """绘制棋子"""
    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            if game.board[row][col]:
                color = BLACK if game.board[row][col] == 'black' else WHITE
                center = (MARGIN + col * GRID_SIZE, MARGIN + row * GRID_SIZE)
                pygame.draw.circle(screen, color, center, PIECE_RADIUS)

def draw_button(text, x, y, width, height, color, text_color=BLACK, disabled=False):
    """绘制按钮"""
    if disabled:
        color = GRAY  # 禁用状态下的颜色
    
    pygame.draw.rect(screen, color, (x, y, width, height))
    text_surface = font.render(text, True, text_color)
    text_rect = text_surface.get_rect(center=(x + width/2, y + height/2))
    screen.blit(text_surface, text_rect)
    return pygame.Rect(x, y, width, height)

def draw_input_box(text, x, y, width, height, active, cursor_visible=False):
    """绘制输入框"""
    color = RED if active else BLACK
    pygame.draw.rect(screen, WHITE, (x, y, width, height))
    pygame.draw.rect(screen, color, (x, y, width, height), 2)
    
    text_surface = font.render(text, True, BLACK)
    # 保持文本在输入框内
    text_width = text_surface.get_width()
    display_text = text
    
    if text_width >= width - 20:
        # 如果文本太长，只显示末尾部分
        visible_text_len = int((width-20)/20)  # 假设每个字符平均宽度为20
        display_text = text[-visible_text_len:]
    
    # 绘制文本
    text_surface = font.render(display_text, True, BLACK)
    screen.blit(text_surface, (x + 10, y + (height - text_surface.get_height()) // 2))
    
    # 绘制光标
    if active and cursor_visible:
        cursor_x = x + 10 + text_surface.get_width()
        cursor_y = y + (height - text_surface.get_height()) // 2
        pygame.draw.line(screen, BLACK, 
                         (cursor_x, cursor_y), 
                         (cursor_x, cursor_y + text_surface.get_height()), 2)
    
    return pygame.Rect(x, y, width, height)

def main():
    game = GomokuClient()
    clock = pygame.time.Clock()
    
    # 初始化UI元素
    server_box = pygame.Rect(WINDOW_SIZE//2 - 150, WINDOW_SIZE//2 - 60, 300, 40)
    username_box = pygame.Rect(WINDOW_SIZE//2 - 150, WINDOW_SIZE//2, 300, 40)
    password_box = pygame.Rect(WINDOW_SIZE//2 - 150, WINDOW_SIZE//2 + 60, 300, 40)
    connect_button = pygame.Rect(WINDOW_SIZE//2 - 60, WINDOW_SIZE//2 + 120, 120, 40)
    
    # 添加颜色选择提交按钮
    color_submit_button = pygame.Rect(WINDOW_SIZE//2 - 60, WINDOW_SIZE//2 + 40, 120, 40)
    
    black_button = pygame.Rect(WINDOW_SIZE//2 - 160, WINDOW_SIZE//2 - 20, 140, 40)
    white_button = pygame.Rect(WINDOW_SIZE//2 + 20, WINDOW_SIZE//2 - 20, 140, 40)
    ready_button = pygame.Rect(WINDOW_SIZE//2 - 50, WINDOW_SIZE//2 + 40, 100, 40)
    restart_button = pygame.Rect(WINDOW_SIZE//2 - 70, WINDOW_SIZE//2 + 60, 140, 40)
    
    # 光标闪烁计时器
    cursor_timer = 0

    while True:
        # 更新光标闪烁状态
        current_time = pygame.time.get_ticks()
        if current_time - cursor_timer > 500:  # 每0.5秒闪烁一次
            game.cursor_visible = not game.cursor_visible
            cursor_timer = current_time
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                
                # 服务器连接阶段
                if game.stage == 'server_connection':
                    if server_box.collidepoint(x, y):
                        game.input_focus = "server"
                    elif username_box.collidepoint(x, y):
                        game.input_focus = "username"
                    elif password_box.collidepoint(x, y):
                        game.input_focus = "password"
                    elif connect_button.collidepoint(x, y):
                        # 尝试连接服务器
                        if game.server_address and game.username:
                            if game.connect_to_server():
                                game.stage = 'authentication'
                                game.send_authentication()
                
                # 身份验证阶段 - 已在连接时处理
                
                # 颜色选择阶段
                elif game.stage == 'color_selection':
                    if black_button.collidepoint(x, y):
                        # 只选择颜色，不立即发送
                        game.selected_color = 'black'
                    elif white_button.collidepoint(x, y):
                        # 只选择颜色，不立即发送
                        game.selected_color = 'white'
                    # 添加提交颜色按钮
                    elif color_submit_button.collidepoint(x, y) and hasattr(game, 'selected_color'):
                        game.select_color(game.selected_color)
                
                # 等待准备阶段
                elif game.stage == 'waiting_ready' and not game.is_ready:
                    if ready_button.collidepoint(x, y):
                        game.send_ready()
                
                # 游戏中
                elif game.stage == 'playing':
                    # 只有点击棋盘内才处理
                    if (MARGIN <= x <= WINDOW_SIZE - MARGIN and 
                        MARGIN <= y <= WINDOW_SIZE - MARGIN):
                        # 计算最近的格点
                        col = round((x - MARGIN) / GRID_SIZE)
                        row = round((y - MARGIN) / GRID_SIZE)
                        # 确保在棋盘范围内
                        if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
                            # 发送移动
                            game.send_move(row, col)
                            print(f"尝试在 ({row},{col}) 放置棋子")
                
                # 游戏结束，可以重新开始
                elif game.stage == 'game_over' and not game.has_voted_restart:
                    if restart_button.collidepoint(x, y):
                        game.vote_restart()
            
            elif event.type == pygame.KEYDOWN:
                # 服务器连接阶段的输入处理
                if game.stage == 'server_connection':
                    if event.key == pygame.K_TAB:
                        # Tab键切换输入焦点
                        if game.input_focus == "server":
                            game.input_focus = "username"
                        elif game.input_focus == "username":
                            game.input_focus = "password"
                        else:
                            game.input_focus = "server"
                    elif event.key == pygame.K_BACKSPACE:
                        # 退格键删除字符
                        if game.input_focus == "server":
                            game.server_address = game.server_address[:-1]
                        elif game.input_focus == "username":
                            game.username = game.username[:-1]
                        elif game.input_focus == "password":
                            game.password_input = game.password_input[:-1]
                    # 注意：这里不再处理回车键，完全依赖按钮点击提交
            
            # 处理文本输入事件，对中文输入更友好
            elif event.type == pygame.TEXTINPUT:
                if game.stage == 'server_connection':
                    if game.input_focus == "server" and len(game.server_address) < 30:
                        game.server_address += event.text
                    elif game.input_focus == "username" and len(game.username) < 15:
                        game.username += event.text
                    elif game.input_focus == "password" and len(game.password_input) < 15:
                        game.password_input += event.text
                    # 重置光标闪烁
                    game.cursor_visible = True
                    cursor_timer = current_time

        # 清屏
        screen.fill(BROWN)
        
        # 根据游戏阶段绘制不同界面
        if game.stage == 'server_connection':
            # 服务器连接界面
            title_text = "五子棋网络对战"
            title_surface = font.render(title_text, True, RED)
            title_rect = title_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 - 150))
            screen.blit(title_surface, title_rect)
            
            # 服务器地址输入
            server_label = "服务器地址:"
            server_surface = font.render(server_label, True, BLACK)
            server_rect = server_surface.get_rect(midright=(WINDOW_SIZE//2 - 160, WINDOW_SIZE//2 - 40))
            screen.blit(server_surface, server_rect)
            
            # 绘制服务器地址输入框
            draw_input_box(game.server_address, server_box.x, server_box.y, 
                          server_box.width, server_box.height, 
                          game.input_focus == "server", game.cursor_visible and game.input_focus == "server")
            
            # 用户名输入
            username_label = "用户名:"
            username_surface = font.render(username_label, True, BLACK)
            username_rect = username_surface.get_rect(midright=(WINDOW_SIZE//2 - 160, WINDOW_SIZE//2 + 20))
            screen.blit(username_surface, username_rect)
            
            # 绘制用户名输入框
            draw_input_box(game.username, username_box.x, username_box.y, 
                          username_box.width, username_box.height, 
                          game.input_focus == "username", game.cursor_visible and game.input_focus == "username")
            
            # 密码输入
            password_label = "密码:"
            password_surface = font.render(password_label, True, BLACK)
            password_rect = password_surface.get_rect(midright=(WINDOW_SIZE//2 - 160, WINDOW_SIZE//2 + 80))
            screen.blit(password_surface, password_rect)
            
            # 绘制密码输入框 (显示为 *)
            masked_password = "*" * len(game.password_input)
            draw_input_box(masked_password, password_box.x, password_box.y, 
                          password_box.width, password_box.height, 
                          game.input_focus == "password", game.cursor_visible and game.input_focus == "password")
            
            # 绘制连接按钮
            connect_disabled = not (game.server_address and game.username and game.password_input)
            draw_button("连接", connect_button.x, connect_button.y, 
                       connect_button.width, connect_button.height, 
                       GREEN, BLACK, connect_disabled)
            
            # 显示错误消息
            if game.error_message:
                error_surface = small_font.render(game.error_message, True, RED)
                error_rect = error_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 + 180))
                screen.blit(error_surface, error_rect)
        
        elif game.stage == 'authentication':
            # 身份验证中
            text = "正在验证身份..."
            text_surface = font.render(text, True, BLUE)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2))
            screen.blit(text_surface, text_rect)
            
            # 显示错误消息
            if game.error_message:
                error_surface = small_font.render(game.error_message, True, RED)
                error_rect = error_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 + 50))
                screen.blit(error_surface, error_rect)
        
        elif game.stage == 'waiting_join':
            # 等待玩家加入
            draw_board()
            
            text = "等待其他玩家加入..."
            text_surface = font.render(text, True, RED)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2))
            screen.blit(text_surface, text_rect)
            
            # 显示当前玩家
            if game.players:
                player_text = "当前玩家:"
                for i, name in enumerate(game.players.keys()):
                    player_text += f" {name}"
                    if i < len(game.players) - 1:
                        player_text += ","
                
                player_surface = small_font.render(player_text, True, BLUE)
                player_rect = player_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 + 40))
                screen.blit(player_surface, player_rect)
        
        elif game.stage == 'color_selection':
            # 颜色选择界面
            draw_board()
            
            text = "请选择棋子颜色:"
            text_surface = font.render(text, True, RED)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 - 60))
            screen.blit(text_surface, text_rect)
            
            # 绘制黑白棋子选择按钮
            my_username = game.username
            black_selected = False
            white_selected = False
            
            for name, info in game.players.items():
                if info['color'] == 'black':
                    black_selected = True
                elif info['color'] == 'white':
                    white_selected = True
            
            # 判断自己是否已选择颜色
            my_color = None
            for name, info in game.players.items():
                if name == my_username and info['color']:
                    my_color = info['color']
            
            if not my_color:
                # 绘制黑棋按钮
                draw_button("黑棋", black_button.x, black_button.y, black_button.width, black_button.height, 
                           BLACK, WHITE, black_selected)
                
                # 绘制白棋按钮
                draw_button("白棋", white_button.x, white_button.y, white_button.width, white_button.height, 
                           WHITE, BLACK, white_selected)
                
                # 绘制提交按钮
                submit_disabled = not hasattr(game, 'selected_color') or game.selected_color is None
                submit_color = GRAY if submit_disabled else GREEN
                draw_button("确认选择", color_submit_button.x, color_submit_button.y, 
                           color_submit_button.width, color_submit_button.height, 
                           submit_color, BLACK, submit_disabled)
                
                # 显示当前选择
                if hasattr(game, 'selected_color') and game.selected_color:
                    selected_text = f"已选择: {'黑棋' if game.selected_color == 'black' else '白棋'} (点击确认提交)"
                    selected_surface = small_font.render(selected_text, True, BLUE)
                    selected_rect = selected_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 + 20))
                    screen.blit(selected_surface, selected_rect)
            else:
                # 已选择颜色，显示等待对手
                text = f"您已选择{my_color}，等待对手选择..."
                text_surface = font.render(text, True, BLUE)
                text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2))
                screen.blit(text_surface, text_rect)
        
        elif game.stage == 'waiting_ready':
            # 准备阶段
            draw_board()
            
            text = "请点击准备开始游戏"
            text_surface = font.render(text, True, RED)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 - 60))
            screen.blit(text_surface, text_rect)
            
            # 显示玩家信息
            y_pos = WINDOW_SIZE//2 - 20
            for name, info in game.players.items():
                color_text = "黑棋" if info['color'] == 'black' else "白棋"
                ready_text = "已准备" if info.get('ready') else "未准备"
                player_text = f"{name} - {color_text} - {ready_text}"
                player_surface = small_font.render(player_text, True, BLUE)
                player_rect = player_surface.get_rect(center=(WINDOW_SIZE//2, y_pos))
                screen.blit(player_surface, player_rect)
                y_pos += 30
            
            # 如果自己还没准备，显示准备按钮
            if not game.is_ready:
                draw_button("准备", ready_button.x, ready_button.y, ready_button.width, ready_button.height, GREEN)
        
        elif game.stage == 'playing':
            # 游戏中，绘制棋盘和棋子
            draw_board()
            draw_pieces(game)
            
            # 显示当前回合
            if game.current_player == 'black':
                current = "黑方"
            else:
                current = "白方"
                
            text = f"当前回合: {current}"
            
            for name, info in game.players.items():
                if info['color'] == game.current_player:
                    text += f" ({name})"
                    break
            
            if game.my_color == game.current_player:
                text += " - 轮到你下棋"
            
            text_surface = font.render(text, True, RED)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, 30))
            screen.blit(text_surface, text_rect)
            
            # 显示玩家信息
            for i, (name, info) in enumerate(game.players.items()):
                color_text = "黑棋" if info['color'] == 'black' else "白棋"
                player_text = f"{name} - {color_text}"
                player_surface = small_font.render(player_text, True, BLUE)
                if i == 0:  # 左侧显示一个玩家
                    player_rect = player_surface.get_rect(midleft=(20, 20))
                else:  # 右侧显示另一个玩家
                    player_rect = player_surface.get_rect(midright=(WINDOW_SIZE - 20, 20))
                screen.blit(player_surface, player_rect)
        
        elif game.stage == 'game_over':
            # 游戏结束，绘制棋盘和棋子
            draw_board()
            draw_pieces(game)
            
            # 显示获胜者
            if game.winner == 'black':
                winner_text = "黑方胜利！"
            else:
                winner_text = "白方胜利！"
            
            # 查找获胜者用户名
            for name, info in game.players.items():
                if info['color'] == game.winner:
                    winner_text += f" ({name})"
                    break
            
            text_surface = font.render(winner_text, True, RED)
            text_rect = text_surface.get_rect(center=(WINDOW_SIZE//2, 30))
            screen.blit(text_surface, text_rect)
            
            # 重新开始按钮
            if not game.has_voted_restart:
                draw_button("重新开始", restart_button.x, restart_button.y, restart_button.width, restart_button.height, GREEN)
            else:
                votes_text = f"等待重新开始 ({game.restart_votes}/2)"
                votes_surface = font.render(votes_text, True, BLUE)
                votes_rect = votes_surface.get_rect(center=(WINDOW_SIZE//2, WINDOW_SIZE//2 + 80))
                screen.blit(votes_surface, votes_rect)

        pygame.display.flip()
        clock.tick(30)  # 限制帧率为30

if __name__ == '__main__':
    main()