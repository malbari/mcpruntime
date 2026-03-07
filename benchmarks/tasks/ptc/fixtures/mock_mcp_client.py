"""Standalone mock MCP client for PTC tasks in isolated environments.

This module is copied to the workspace so PTC tasks can import it in Docker/subprocess.
Provides a comprehensive set of tools for testing Programmatic Tool Calling.
"""

import random
import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def call_mcp_tool(tool_name: str, method: str, args: Optional[Dict] = None) -> Any:
    """Mock implementation of MCP tool calling for PTC tasks.

    Args:
        tool_name: Name of the tool ('calculator', 'weather', 'filesystem', 
                   'database', 'http', 'text', 'email', 'calendar', 'math')
        method: Method to call on the tool
        args: Arguments for the method

    Returns:
        Mock result based on tool and method
    """
    args = args or {}

    if tool_name == 'calculator':
        return _handle_calculator(method, args)
    elif tool_name == 'weather':
        return _handle_weather(method, args)
    elif tool_name == 'filesystem':
        return _handle_filesystem(method, args)
    elif tool_name == 'database':
        return _handle_database(method, args)
    elif tool_name == 'http':
        return _handle_http(method, args)
    elif tool_name == 'text':
        return _handle_text(method, args)
    elif tool_name == 'email':
        return _handle_email(method, args)
    elif tool_name == 'calendar':
        return _handle_calendar(method, args)
    elif tool_name == 'math':
        return _handle_math(method, args)
    elif tool_name == 'transform':
        return _handle_transform(method, args)
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


# ============================================================================
# CALCULATOR TOOL
# ============================================================================

def _handle_calculator(method: str, args: Dict) -> Any:
    """Handle calculator tool methods."""
    if method == 'add':
        return args.get('a', 0) + args.get('b', 0)
    elif method == 'subtract':
        return args.get('a', 0) - args.get('b', 0)
    elif method == 'multiply':
        return args.get('a', 0) * args.get('b', 0)
    elif method == 'divide':
        b = args.get('b', 1)
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return args.get('a', 0) / b
    elif method == 'power':
        return args.get('base', 0) ** args.get('exponent', 1)
    elif method == 'sqrt':
        import math
        return math.sqrt(args.get('n', 0))
    elif method == 'calculate':
        expr = args.get('expression', '')
        return _safe_eval(expr)
    elif method == 'sum_list':
        return sum(args.get('numbers', []))
    elif method == 'avg_list':
        numbers = args.get('numbers', [])
        return sum(numbers) / len(numbers) if numbers else 0
    else:
        raise ValueError(f"Unknown calculator method: {method}")


def _safe_eval(expr: str) -> float:
    """Safely evaluate a mathematical expression without using eval()."""
    expr = expr.replace(' ', '').replace('**', '^')
    
    # Handle power operator
    while '^' in expr:
        match = re.search(r'(\d+\.?\d*)\^(\d+\.?\d*)', expr)
        if match:
            base = float(match.group(1))
            exp = float(match.group(2))
            result = base ** exp
            expr = expr[:match.start()] + str(result) + expr[match.end():]
        else:
            break
    
    # Handle parentheses
    while '(' in expr:
        start = expr.rfind('(')
        end = expr.find(')', start)
        if end == -1:
            raise ValueError("Mismatched parentheses")
        inner = expr[start + 1:end]
        inner_result = _safe_eval_simple(inner)
        expr = expr[:start] + str(inner_result) + expr[end + 1:]
    
    return _safe_eval_simple(expr)


def _safe_eval_simple(expr: str) -> float:
    """Evaluate expression without parentheses (order of operations)."""
    tokens = _tokenize(expr)
    tokens = _apply_ops(tokens, ['*', '/'])
    tokens = _apply_ops(tokens, ['+', '-'])
    return float(tokens[0])


def _tokenize(expr: str) -> list:
    """Tokenize expression into numbers and operators."""
    tokens = []
    current = ''
    for char in expr:
        if char in '+-*/':
            if current:
                tokens.append(float(current))
                current = ''
            tokens.append(char)
        else:
            current += char
    if current:
        tokens.append(float(current))
    return tokens


def _apply_ops(tokens: list, ops: list) -> list:
    """Apply operations left to right."""
    result = [tokens[0]]
    i = 1
    while i < len(tokens):
        if tokens[i] in ops:
            left = result[-1]
            right = tokens[i + 1]
            if tokens[i] == '*':
                result[-1] = left * right
            elif tokens[i] == '/':
                result[-1] = left / right
            elif tokens[i] == '+':
                result[-1] = left + right
            elif tokens[i] == '-':
                result[-1] = left - right
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


# ============================================================================
# WEATHER TOOL
# ============================================================================

def _handle_weather(method: str, args: Dict) -> Dict:
    """Handle weather tool methods."""
    location = args.get('location', 'Unknown')
    units = args.get('units', 'celsius')
    loc_hash = sum(ord(c) for c in location) % 15
    
    if units == 'celsius':
        base_temp = 15 + loc_hash
    else:
        base_temp = 59 + (loc_hash * 9 // 5)
    
    conditions = ['sunny', 'cloudy', 'partly cloudy', 'rainy', 'windy', 'snowy', 'foggy']
    condition = conditions[loc_hash % len(conditions)]
    
    if method == 'get_weather':
        return {
            'location': location,
            'temperature': base_temp,
            'unit': units,
            'condition': condition,
            'humidity': 40 + (loc_hash * 2),
            'wind_speed': 5 + loc_hash,
            'pressure': 1013 + (loc_hash - 7) * 2,
            'timestamp': datetime.now().isoformat(),
        }
    elif method == 'get_forecast':
        days = args.get('days', 5)
        forecast = []
        for i in range(days):
            day_temp = base_temp + (i % 5) - 2
            forecast.append({
                'day': i + 1,
                'temperature': day_temp,
                'condition': conditions[(loc_hash + i) % len(conditions)],
                'date': (datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d'),
            })
        return {
            'location': location,
            'unit': units,
            'forecast': forecast,
        }
    elif method == 'get_historical':
        # Return past 7 days of weather
        days_back = args.get('days_back', 7)
        history = []
        for i in range(days_back):
            day_temp = base_temp + ((loc_hash + i) % 5) - 3
            history.append({
                'date': (datetime.now() - timedelta(days=i+1)).strftime('%Y-%m-%d'),
                'temperature': day_temp,
                'condition': conditions[(loc_hash + i + 3) % len(conditions)],
            })
        return {'location': location, 'unit': units, 'history': history}
    elif method == 'compare_locations':
        locations = args.get('locations', [])
        temps = {}
        for loc in locations:
            loc_h = sum(ord(c) for c in loc) % 15
            temps[loc] = 15 + loc_h if units == 'celsius' else 59 + (loc_h * 9 // 5)
        return {'location': location, 'comparisons': temps, 'unit': units}
    else:
        raise ValueError(f"Unknown weather method: {method}")


# ============================================================================
# FILESYSTEM TOOL
# ============================================================================

def _handle_filesystem(method: str, args: Dict) -> Any:
    """Handle filesystem tool methods."""
    import os
    
    path = args.get('path', '')
    
    if method == 'read_file':
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
    elif method == 'write_file':
        content = args.get('content', '')
        with open(path, 'w') as f:
            f.write(content)
        return True
    elif method == 'append_file':
        content = args.get('content', '')
        with open(path, 'a') as f:
            f.write(content)
        return True
    elif method == 'list_directory':
        try:
            return os.listdir(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Directory not found: {path}")
    elif method == 'file_exists':
        return os.path.exists(path)
    elif method == 'get_size':
        try:
            return os.path.getsize(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
    elif method == 'read_lines':
        try:
            with open(path, 'r') as f:
                return f.readlines()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
    elif method == 'count_lines':
        try:
            with open(path, 'r') as f:
                return len(f.readlines())
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")
    else:
        raise ValueError(f"Unknown filesystem method: {method}")


# ============================================================================
# DATABASE TOOL
# ============================================================================

_MOCK_DB = {
    'users': [
        {'id': 1, 'name': 'Alice', 'age': 25, 'email': 'alice@example.com', 'city': 'Berlin', 'salary': 50000},
        {'id': 2, 'name': 'Bob', 'age': 30, 'email': 'bob@example.com', 'city': 'Paris', 'salary': 60000},
        {'id': 3, 'name': 'Carol', 'age': 35, 'email': 'carol@example.com', 'city': 'London', 'salary': 75000},
        {'id': 4, 'name': 'David', 'age': 40, 'email': 'david@example.com', 'city': 'Berlin', 'salary': 80000},
        {'id': 5, 'name': 'Eve', 'age': 45, 'email': 'eve@example.com', 'city': 'Tokyo', 'salary': 90000},
        {'id': 6, 'name': 'Frank', 'age': 28, 'email': 'frank@example.com', 'city': 'Paris', 'salary': 55000},
        {'id': 7, 'name': 'Grace', 'age': 33, 'email': 'grace@example.com', 'city': 'London', 'salary': 70000},
        {'id': 8, 'name': 'Henry', 'age': 50, 'email': 'henry@example.com', 'city': 'Berlin', 'salary': 100000},
    ],
    'products': [
        {'id': 1, 'name': 'Widget', 'price': 9.99, 'stock': 100, 'category': 'electronics'},
        {'id': 2, 'name': 'Gadget', 'price': 19.99, 'stock': 50, 'category': 'electronics'},
        {'id': 3, 'name': 'Tool', 'price': 29.99, 'stock': 25, 'category': 'hardware'},
        {'id': 4, 'name': 'Device', 'price': 49.99, 'stock': 75, 'category': 'electronics'},
        {'id': 5, 'name': 'Component', 'price': 14.99, 'stock': 200, 'category': 'hardware'},
    ],
    'orders': [
        {'id': 1, 'user_id': 1, 'product_id': 1, 'quantity': 2, 'date': '2024-01-15', 'status': 'completed'},
        {'id': 2, 'user_id': 2, 'product_id': 3, 'quantity': 1, 'date': '2024-01-16', 'status': 'pending'},
        {'id': 3, 'user_id': 1, 'product_id': 2, 'quantity': 5, 'date': '2024-01-17', 'status': 'completed'},
        {'id': 4, 'user_id': 3, 'product_id': 4, 'quantity': 1, 'date': '2024-01-18', 'status': 'completed'},
        {'id': 5, 'user_id': 4, 'product_id': 5, 'quantity': 3, 'date': '2024-01-19', 'status': 'shipped'},
    ],
}


def _handle_database(method: str, args: Dict) -> Any:
    """Handle database tool methods."""
    table = args.get('table', '')
    
    if method == 'query':
        columns = args.get('columns', [])
        where = args.get('where', {})
        data = _MOCK_DB.get(table, [])
        
        # Filter by where clause
        if where:
            data = [row for row in data if all(row.get(k) == v for k, v in where.items())]
        
        # Filter columns
        if columns:
            data = [{k: v for k, v in row.items() if k in columns} for row in data]
        
        return data
    
    elif method == 'aggregate':
        agg_type = args.get('type', 'count')
        column = args.get('column', '')
        where = args.get('where', {})
        data = _MOCK_DB.get(table, [])
        
        if where:
            data = [row for row in data if all(row.get(k) == v for k, v in where.items())]
        
        if agg_type == 'count':
            return len(data)
        elif agg_type == 'sum':
            return sum(row.get(column, 0) for row in data)
        elif agg_type == 'avg':
            values = [row.get(column, 0) for row in data]
            return sum(values) / len(values) if values else 0
        elif agg_type == 'max':
            return max((row.get(column, 0) for row in data), default=0)
        elif agg_type == 'min':
            return min((row.get(column, float('inf')) for row in data), default=0)
        else:
            raise ValueError(f"Unknown aggregate type: {agg_type}")
    
    elif method == 'join':
        join_table = args.get('join_table', '')
        on = args.get('on', '')
        left = _MOCK_DB.get(table, [])
        right = _MOCK_DB.get(join_table, [])
        
        result = []
        for l_row in left:
            for r_row in right:
                if l_row.get(on) == r_row.get(on):
                    joined = {**l_row}
                    for k, v in r_row.items():
                        if k not in joined:
                            joined[f"{join_table}_{k}"] = v
                    result.append(joined)
        return result
    
    else:
        raise ValueError(f"Unknown database method: {method}")


# ============================================================================
# HTTP TOOL
# ============================================================================

def _handle_http(method: str, args: Dict) -> Any:
    """Handle HTTP API tool methods."""
    url = args.get('url', '')
    
    # Mock API endpoints
    if method == 'get':
        if 'users' in url or 'user' in url:
            return {'data': _MOCK_DB['users'][:3], 'status': 200}
        elif 'weather' in url:
            return {'data': {'temp': 22, 'condition': 'sunny'}, 'status': 200}
        elif 'products' in url:
            return {'data': _MOCK_DB['products'][:3], 'status': 200}
        else:
            return {'data': {'message': 'Mock data'}, 'status': 200}
    
    elif method == 'post':
        data = args.get('data', {})
        return {'data': {'id': 999, **data}, 'status': 201}
    
    elif method == 'put':
        data = args.get('data', {})
        return {'data': {'updated': True, **data}, 'status': 200}
    
    elif method == 'delete':
        return {'data': {'deleted': True}, 'status': 200}
    
    elif method == 'fetch_json':
        # Return mock JSON data
        return {'users': _MOCK_DB['users'][:5], 'count': 5}
    
    else:
        raise ValueError(f"Unknown HTTP method: {method}")


# ============================================================================
# TEXT TOOL
# ============================================================================

def _handle_text(method: str, args: Dict) -> Any:
    """Handle text processing tool methods."""
    text = args.get('text', '')
    
    if method == 'split':
        delimiter = args.get('delimiter', ' ')
        return text.split(delimiter)
    
    elif method == 'join':
        items = args.get('items', [])
        delimiter = args.get('delimiter', ' ')
        return delimiter.join(str(x) for x in items)
    
    elif method == 'search':
        pattern = args.get('pattern', '')
        return pattern in text
    
    elif method == 'replace':
        old = args.get('old', '')
        new = args.get('new', '')
        return text.replace(old, new)
    
    elif method == 'regex_match':
        pattern = args.get('pattern', '')
        return bool(re.search(pattern, text))
    
    elif method == 'regex_findall':
        pattern = args.get('pattern', '')
        return re.findall(pattern, text)
    
    elif method == 'to_upper':
        return text.upper()
    
    elif method == 'to_lower':
        return text.lower()
    
    elif method == 'strip':
        return text.strip()
    
    elif method == 'word_count':
        return len(text.split())
    
    elif method == 'line_count':
        return len(text.split('\n'))
    
    else:
        raise ValueError(f"Unknown text method: {method}")


# ============================================================================
# EMAIL TOOL
# ============================================================================

def _handle_email(method: str, args: Dict) -> Any:
    """Handle email tool methods."""
    if method == 'send':
        to = args.get('to', '')
        subject = args.get('subject', '')
        body = args.get('body', '')
        return {'sent': True, 'id': f"email_{hash(to+subject)%10000}", 'to': to}
    
    elif method == 'fetch':
        # Mock inbox
        return [
            {'id': 1, 'from': 'alice@example.com', 'subject': 'Meeting', 'date': '2024-01-15'},
            {'id': 2, 'from': 'bob@example.com', 'subject': 'Report', 'date': '2024-01-16'},
            {'id': 3, 'from': 'carol@example.com', 'subject': 'Update', 'date': '2024-01-17'},
        ]
    
    elif method == 'search':
        query = args.get('query', '')
        return [
            {'id': 1, 'from': 'alice@example.com', 'subject': f'About {query}', 'date': '2024-01-15'},
        ]
    
    else:
        raise ValueError(f"Unknown email method: {method}")


# ============================================================================
# CALENDAR TOOL
# ============================================================================

def _handle_calendar(method: str, args: Dict) -> Any:
    """Handle calendar tool methods."""
    if method == 'create_event':
        title = args.get('title', '')
        date = args.get('date', datetime.now().strftime('%Y-%m-%d'))
        return {'created': True, 'id': f"evt_{hash(title+date)%10000}", 'title': title, 'date': date}
    
    elif method == 'list_events':
        start = args.get('start_date', '2024-01-01')
        end = args.get('end_date', '2024-12-31')
        return [
            {'id': 1, 'title': 'Meeting', 'date': '2024-01-15', 'time': '10:00'},
            {'id': 2, 'title': 'Review', 'date': '2024-01-16', 'time': '14:00'},
            {'id': 3, 'title': 'Planning', 'date': '2024-01-17', 'time': '09:00'},
        ]
    
    elif method == 'delete_event':
        event_id = args.get('event_id', '')
        return {'deleted': True, 'id': event_id}
    
    elif method == 'count_events':
        return {'count': 3}
    
    else:
        raise ValueError(f"Unknown calendar method: {method}")


# ============================================================================
# MATH TOOL
# ============================================================================

def _handle_math(method: str, args: Dict) -> Any:
    """Handle advanced math tool methods."""
    if method == 'fibonacci':
        n = args.get('n', 0)
        if n <= 0:
            return []
        elif n == 1:
            return [0]
        fib = [0, 1]
        for i in range(2, n):
            fib.append(fib[-1] + fib[-2])
        return fib[:n]
    
    elif method == 'factorial':
        n = args.get('n', 0)
        result = 1
        for i in range(2, n + 1):
            result *= i
        return result
    
    elif method == 'gcd':
        a = args.get('a', 0)
        b = args.get('b', 0)
        while b:
            a, b = b, a % b
        return a
    
    elif method == 'lcm':
        a = args.get('a', 1)
        b = args.get('b', 1)
        def _gcd(x, y):
            while y:
                x, y = y, x % y
            return x
        return abs(a * b) // _gcd(a, b) if a and b else 0
    
    elif method == 'is_prime':
        n = args.get('n', 0)
        if n < 2:
            return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0:
                return False
        return True
    
    elif method == 'primes_up_to':
        n = args.get('n', 0)
        sieve = [True] * (n + 1)
        sieve[0] = sieve[1] = False
        for i in range(2, int(n**0.5) + 1):
            if sieve[i]:
                for j in range(i*i, n + 1, i):
                    sieve[j] = False
        return [i for i, is_p in enumerate(sieve) if is_p]
    
    else:
        raise ValueError(f"Unknown math method: {method}")


# ============================================================================
# TRANSFORM TOOL (data transformation)
# ============================================================================

def _handle_transform(method: str, args: Dict) -> Any:
    """Handle data transformation tool methods."""
    data = args.get('data', [])
    
    if method == 'sort_by':
        key = args.get('key', '')
        reverse = args.get('reverse', False)
        return sorted(data, key=lambda x: x.get(key, 0), reverse=reverse)
    
    elif method == 'filter':
        key = args.get('key', '')
        value = args.get('value', '')
        return [x for x in data if x.get(key) == value]
    
    elif method == 'map_field':
        field = args.get('field', '')
        return [x.get(field) for x in data if field in x]
    
    elif method == 'group_by':
        key = args.get('key', '')
        groups = {}
        for item in data:
            k = item.get(key)
            groups.setdefault(k, []).append(item)
        return groups
    
    elif method == 'sum_field':
        field = args.get('field', '')
        return sum(x.get(field, 0) for x in data)
    
    elif method == 'count_by':
        field = args.get('field', '')
        from collections import Counter
        return dict(Counter(x.get(field) for x in data))
    
    elif method == 'unique_values':
        field = args.get('field', '')
        return list(set(x.get(field) for x in data if field in x))
    
    else:
        raise ValueError(f"Unknown transform method: {method}")
