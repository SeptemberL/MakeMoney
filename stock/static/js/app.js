// 全局变量
let currentStock = null;
let charts = {
    kline: null,
    volume: null,
    indicator: null
};
let ws = null; // WebSocket连接
let realtimeUpdateInterval = null; // 实时更新定时器

// MACD参数
let macdParams = {
    ema_short: 12,
    ema_long: 26,
    dea_period: 9
};

// 添加视图状态变量
let viewsState = {
    macd: true,
    indicator: true
};

// 添加指标显示状态变量
let indicatorSettings = {
    // 第一视图
    showBoll: true,
    showMA5: false,
    showMA10: false,
    showMA20: false,
    // 第二视图
    showMACD: true,
    showSignal: true,
    showHistogram: true,
    // 第三视图
    showRSI6: true,
    showRSI12: true,
    showRSI24: true,
    showK: true,
    showD: true,
    showJ: true,
    showVolume: true,
    showVolumeMA5: true,
    showVolumeMA10: true
};

// 用户相关变量
let currentUser = null;

// 初始化图表
function initCharts() {
    // 创建空的图表
    const emptyData = [{
        type: 'scatter',
        x: [],
        y: []
    }];

    const defaultLayout = {
        showlegend: false,
        xaxis: { rangeslider: { visible: false } }
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    // 初始化K线图和MACD图
    Plotly.newPlot('klineChart', emptyData, defaultLayout, config);
    Plotly.newPlot('macdChart', emptyData, defaultLayout, config);
}

function updateBoll3(displayData, klineData)
{
    klineData.push(
        // BOLL中轨
        {
            type: 'scatter',
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_mid),
            name: 'BOLL中轨',
            line: { color: '#FFAEC9', width: 1 },
            visible: true
        },
        // BOLL 2倍标准差上轨
        {
            type: 'scatter',
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_upper2),
            name: 'BOLL 2σ上轨',
            line: { color: '#FFC90E', width: 1 },
            visible: true
        },
        // BOLL 2倍标准差下轨
        {
            type: 'scatter',
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_lower2),
            name: 'BOLL 2σ下轨',
            line: { color: '#0CAEE6', width: 1 },
            visible: true
        },
        // BOLL 3倍标准差上轨
        {
            type: 'scatter',
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_upper3),
            name: 'BOLL 3σ上轨',
            line: { color: '#00C90E', width: 1 },
            visible: true
        },
        // BOLL 3倍标准差下轨
        {
            type: 'scatter',
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_lower3),
            name: 'BOLL 3σ下轨',
            line: { color: '#FFAEE6', width: 1 },
            visible: true
        },
        {
            type: 'scatter',
            mode: 'markers+text',  // 显示标记和文字
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_lower2),
            text: displayData.map(item => item.LOWER_BREAK ? '下轨突破' : ''),  // 根据LOWER_BREAK的值决定显示文本
            textposition: 'bottom right',
            showarrow: true,
            arrowhead: 2,
            arrowsize: 1,
            arrowcolor: 'red',
            visible: displayData.map(item => item.LOWER_BREAK == 1)
          },
          {
            type: 'scatter',
            mode: 'markers+text',  // 显示标记和文字
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_lower3),
            text: displayData.map(item => item.LOWER_REVERSE ? '下轨反转' : ''),  // 根据LOWER_BREAK的值决定显示文本
            textposition: 'bottom right',
            showarrow: true,
            arrowhead: 2,
            arrowsize: 1,
            arrowcolor: 'red',
            visible: displayData.map(item => item.LOWER_REVERSE == 1)
          },
          {
            type: 'scatter',
            mode: 'markers+text',  // 显示标记和文字
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_upper2),
            text: displayData.map(item => item.UPPER_BREAK ? '上轨突破' : ''),  // 根据LOWER_BREAK的值决定显示文本
            textposition: 'up left',
            showarrow: true,
            arrowhead: 2,
            arrowsize: 1,
            arrowcolor: 'red',
            visible: displayData.map(item => item.UPPER_BREAK == 1)
          },
          {
            type: 'scatter',
            mode: 'markers+text',  // 显示标记和文字
            x: displayData.map(item => item.trade_date),
            y: displayData.map(item => item.boll3_upper3),
            text: displayData.map(item => item.UPPER_REVERSE ? '上轨反转' : ''),  // 根据LOWER_BREAK的值决定显示文本
            textposition: 'up right',
            showarrow: true,
            arrowhead: 2,
            arrowsize: 1,
            arrowcolor: 'red',
            visible: displayData.map(item => item.UPPER_REVERSE == 1)
          }
    );
}


function updateDLJG(displayData, macdData)
{
    macdData.push({
        type: 'scatter',
        x: displayData.map(item => item.trade_date),
        y: displayData.map(item => item.dljg2_macd),
        name: 'MACD',
        line: { color: '#FF9800', width: 1 },
        visible: true
    });

    macdData.push({
        type: 'bar',
        x: displayData.map(item => item.trade_date),
        y: displayData.map(item => item.dljg2_hist),
        name: 'Histogram',
        marker: {
            color: displayData.map(item => item.macd_hist >= 0 ? 'rgba(255,0,0,0.8)' : 'rgba(0,255,0,0.8)')
        },
        visible: true
    });

    macdData.push({
        type: 'scatter',
        x: displayData.map(item => item.trade_date),
        y: displayData.map(item => item.dljg2_signal),
        name: 'Signal',
        line: { color: '#2196F3', width: 1 },
        visible: true
    });

}

// 更新图表
function updateCharts(data) {
    if (!data || data.length === 0) {
        console.error('No data to display');
        return;
    }
    
    // 确保数据按日期排序
    data.sort((a, b) => new Date(a.trade_date) - new Date(b.trade_date));
    
    // 只取最近50天的数据用于显示
    const displayData = data.slice(-100);

    // 设置基础配置
    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    try {
        // K线图和BOLL数据
        const klineData = [
            // K线数据
            {
                type: 'candlestick',
                x: displayData.map(item => item.trade_date),
                open: displayData.map(item => item.open),
                high: displayData.map(item => item.high),
                low: displayData.map(item => item.low),
                close: displayData.map(item => item.close),
                name: 'K线',
                increasing: {line: {color: '#FF0000'}},
                decreasing: {line: {color: '#00FF00'}},
                xaxis: 'x',
                yaxis: 'y',
                visible: true
            }
        ];

        // 根据设置添加BOLL指标
        if (indicatorSettings.showBoll) {
           updateBoll3(displayData, klineData)
        }

        // 根据设置添加均线
        if (indicatorSettings.showMA5) {
            klineData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.ma5),
                name: 'MA5',
                line: { color: '#FF9800', width: 1 },
                visible: true
            });
        }
        if (indicatorSettings.showMA10) {
            klineData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.ma10),
                name: 'MA10',
                line: { color: '#2196F3', width: 1 },
                visible: true
            });
        }
        if (indicatorSettings.showMA20) {
            klineData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.ma20),
                name: 'MA20',
                line: { color: '#4CAF50', width: 1 },
                visible: true
            });
        }

        // MACD数据
        const macdData = [];
        if (indicatorSettings.showMACD) {
            updateDLJG(displayData, macdData)
        }


        // 技术指标数据
        const indicatorData = [];
        if (indicatorSettings.showRSI6) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.rsi_6),
                name: 'RSI(6)',
                line: { color: '#FF9800' },
                visible: true
            });
        }
        if (indicatorSettings.showRSI12) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.rsi_12),
                name: 'RSI(12)',
                line: { color: '#2196F3' },
                visible: true
            });
        }
        if (indicatorSettings.showRSI24) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.rsi_24),
                name: 'RSI(24)',
                line: { color: '#4CAF50' },
                visible: true
            });
        }
        if (indicatorSettings.showK) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.k),
                name: 'K',
                line: { color: '#FF5722' },
                visible: true
            });
        }
        if (indicatorSettings.showD) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.d),
                name: 'D',
                line: { color: '#9C27B0' },
                visible: true
            });
        }
        if (indicatorSettings.showJ) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.j),
                name: 'J',
                line: { color: '#00BCD4' },
                visible: true
            });
        }
        if (indicatorSettings.showVolume) {
            indicatorData.push({
                type: 'bar',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.volume),
                name: '成交量',
                yaxis: 'y2',
                marker: {
                    color: displayData.map(item => 
                        item.close >= item.open ? 'rgba(255,0,0,0.5)' : 'rgba(0,255,0,0.5)'
                    )
                },
                visible: true
            });
        }
        if (indicatorSettings.showVolumeMA5) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.volume_ma5),
                name: '成交量MA5',
                yaxis: 'y2',
                line: { color: '#FFC107' },
                visible: true
            });
        }
        if (indicatorSettings.showVolumeMA10) {
            indicatorData.push({
                type: 'scatter',
                x: displayData.map(item => item.trade_date),
                y: displayData.map(item => item.volume_ma10),
                name: '成交量MA10',
                yaxis: 'y2',
                line: { color: '#795548' },
                visible: true
            });
        }

        // 设置图表布局
        const klineLayout = {
            title: 'K线图 & BOLL',
            dragmode: 'zoom',
            showlegend: true,
            legend: {
                x: 0,
                y: 1,
                orientation: 'h',
                yanchor: 'bottom'
            },
            xaxis: {
                title: '日期',
                rangeslider: { visible: false },
                type: 'category',
                tickangle: -45
            },
            yaxis: {
                title: '价格',
                autorange: true,
                fixedrange: false
            },
            height: 500,
            margin: { t: 40, l: 60, r: 40, b: 40 },
            plot_bgcolor: 'white',  // 白色背景
            paper_bgcolor: 'white'
        };

        const macdLayout = {
            title: 'MACD',
            showlegend: true,
            legend: {
                x: 0,
                y: 1,
                orientation: 'h'
            },
            xaxis: {
                title: '日期',
                type: 'category',
                tickangle: -45,
                tickformat: '%Y-%m-%d'
            },
            yaxis: {
                title: 'MACD',
                fixedrange: false
            },
            height: 500,
            margin: { t: 40, l: 60, r: 40, b: 40 },
            plot_bgcolor: 'white',
            paper_bgcolor: 'white'
        };

        // 绘制图表
        Plotly.react('klineChart', klineData, klineLayout, config);
        Plotly.react('macdChart', macdData, macdLayout, config);

        // 添加技术指标图表
        const indicatorLayout = {
            title: '技术指标',
            showlegend: true,
            legend: {
                x: 0,
                y: 1,
                orientation: 'h'
            },
            xaxis: {
                title: '日期',
                type: 'category',
                tickangle: -45
            },
            yaxis: {
                title: 'RSI/KDJ',
                domain: [0.6, 1]
            },
            yaxis2: {
                title: '成交量',
                domain: [0, 0.4],
                overlaying: 'y',
                side: 'right'
            },
            height: 500,
            margin: { t: 40, l: 60, r: 60, b: 40 },
            plot_bgcolor: 'white',
            paper_bgcolor: 'white'
        };

        // 绘制技术指标图表
        Plotly.react('indicatorChart', indicatorData, indicatorLayout, config);

    } catch (error) {
        console.error('更新图表时出错:', error);
    }
}

// 加载股票列表
function loadStockList() {
    $.get('/api/stocks', function(stocks) {
        const stockListHtml = stocks.map(stock => `
            <div class="stock-item">
                <div>
                    <strong>${stock.code}</strong>
                    ${stock.name ? `<span class="text-muted">(${stock.name})</span>` : ''}
                </div>
                <div>
                    <button class="btn btn-sm btn-primary" onclick="loadStockData('${stock.code}')">查看</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteStock('${stock.code}')">删除</button>
                </div>
            </div>
        `).join('');
        
        $('#stockList').html(stockListHtml);
    });
}

// 添加股票
function addStock(event) {
    event.preventDefault();
    
    const stockCode = $('#stockCode').val().trim();
    const stockName = $('#stockName').val().trim();
    
    if (!stockCode) {
        alert('请输入股票代码');
        return false;
    }
    
    $.ajax({
        url: '/api/stocks',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            code: stockCode,
            name: stockName
        }),
        success: function(response) {
            if (response.success) {
                alert('添加成功');
                $('#stockCode').val('');
                $('#stockName').val('');
                loadStockList();
            } else {
                alert('添加失败: ' + response.error);
            }
        },
        error: function(xhr) {
            alert('添加失败: ' + xhr.responseJSON?.error || '未知错误');
        }
    });
    
    return false;
}

// 删除股票
function deleteStock(stockCode) {
    if (confirm(`确定要删除股票 ${stockCode} 吗？`)) {
        $.ajax({
            url: `/api/stocks/${stockCode}`,
            method: 'DELETE',
            success: function() {
                loadStockList();
            },
            error: function(xhr) {
                alert('删除失败: ' + xhr.responseJSON?.error || '未知错误');
            }
        });
    }
}

// 初始化WebSocket连接
function initWebSocket(stockCode) {
    // 如果已有连接，先关闭
    if (ws) {
        ws.close();
    }
    
    // 创建新的WebSocket连接
    ws = new WebSocket(`ws://${window.location.host}/ws/stock_realtime/${stockCode}`);
    
    ws.onopen = function() {
        console.log('WebSocket连接已建立');
    };
    
    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'kline_update') {
            updateRealtimeKline(data.data);
        }
    };
    
    ws.onclose = function() {
        console.log('WebSocket连接已关闭');
        // 尝试重新连接
        setTimeout(() => {
            if (currentStock) {
                initWebSocket(currentStock);
            }
        }, 5000);
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket错误:', error);
    };
}

// 更新实时K线数据
function updateRealtimeKline(newData) {
    if (!currentStock) return;
    
    // 获取当前图表数据
    const klineChart = document.getElementById('klineChart');
    const currentData = klineChart.data;
    
    // 更新K线数据
    if (currentData && currentData.length > 0) {
        const klineData = currentData[0]; // K线数据是第一个系列
        
        // 检查是否是新的一天
        const lastDate = klineData.x[klineData.x.length - 1];
        if (newData.trade_date === lastDate) {
            // 更新当天的数据
            klineData.open[klineData.open.length - 1] = newData.open;
            klineData.high[klineData.high.length - 1] = newData.high;
            klineData.low[klineData.low.length - 1] = newData.low;
            klineData.close[klineData.close.length - 1] = newData.close;
        } else {
            // 添加新的K线数据
            klineData.x.push(newData.trade_date);
            klineData.open.push(newData.open);
            klineData.high.push(newData.high);
            klineData.low.push(newData.low);
            klineData.close.push(newData.close);
            
            // 保持最近100天的数据
            if (klineData.x.length > 100) {
                klineData.x.shift();
                klineData.open.shift();
                klineData.high.shift();
                klineData.low.shift();
                klineData.close.shift();
            }
        }
        
        // 更新图表
        Plotly.react('klineChart', currentData, klineChart.layout, klineChart.config);
    }
}

// 修改loadStockData函数
function loadStockData(stockCode) {
    console.log('开始加载股票数据:', stockCode);
    currentStock = stockCode;
    
    // 初始化WebSocket连接
    initWebSocket(stockCode);
    
    $.get(`/api/stock_data/${stockCode}`, function(response) {
        if (response.error) {
            console.error('加载数据错误:', response.error);
            alert('获取数据失败: ' + response.error);
            return;
        }
        
        if (!response.data || response.data.length === 0) {
            console.error('没有收到数据');
            alert('没有获取到股票数据');
            return;
        }

        // 处理日期格式
        const processedData = response.data.map(item => ({
            ...item,
            trade_date: new Date(item.trade_date).toISOString().split('T')[0]
        }));

        // 更新图表和信息（兼容旧接口：缺省为 [] / null / {}）
        updateCharts(processedData);
        updateSignals(response.signals || [], response.amplitude || null);
        updateProbabilities(response.probabilities || {});
    }).fail(function(xhr, status, error) {
        console.error('Ajax请求失败:', {
            status: status,
            error: error,
            response: xhr.responseText
        });
        alert('获取数据失败，请查看控制台');
    });
}

// 更新信号列表
function updateSignals(signals, amplitude) {
    let signalHtml = '';
    
    // 添加振幅信息
    if (amplitude) {
        signalHtml += `
            <div class="alert alert-info">
                <h5>振幅分析（200天）</h5>
                <div>平均振幅: ${amplitude.average_amplitude}%</div>
                <div>最大振幅: ${amplitude.max_amplitude}%</div>
                <div>最小振幅: ${amplitude.min_amplitude}%</div>
                <div>最新振幅: ${amplitude.latest_amplitude}%</div>
            </div>
        `;
    }
    
    // 添加原有的信号（signals 保证为数组）
    const list = Array.isArray(signals) ? signals : [];
    signalHtml += list.map(signal => `
        <div class="alert alert-${signal.signal === 'BUY' ? 'success' : 'danger'}">
            <strong>${signal.type}</strong>: ${signal.message}
            <span class="badge bg-secondary">${signal.strength}</span>
        </div>
    `).join('');
    
    $('#signalList').html(signalHtml);
}

// 更新概率分析
function updateProbabilities(probabilities) {
    const obj = probabilities && typeof probabilities === 'object' ? probabilities : {};
    const probHtml = Object.entries(obj).map(([key, value]) => `
        <div class="mb-2">
            <strong>${key}</strong>: ${(value * 100).toFixed(2)}%
        </div>
    `).join('');
    
    $('#probabilityList').html(probHtml);
}

// 更新所有股票
function updateAllStocks() {
    // 显示更新中状态
    const statusSpan = $('#updateStocksStatus');
    statusSpan.html('<span class="text-warning">正在更新所有股票数据...</span>');
    
    // 禁用按钮
    const button = $(event.target);
    button.prop('disabled', true);
    
    // 发送更新请求
    $.ajax({
        url: '/api/update_all_stocks',
        method: 'POST',
        success: function(response) {
            if (response.success) {
                statusSpan.html(`<span class="text-success">
                    更新成功！共更新 ${response.updated_count} 只股票
                    ${response.failed_stocks.length > 0 ? 
                      `<br>失败: ${response.failed_stocks.join(', ')}` : ''}
                </span>`);
                
                // 如果有股票更新成功，刷新当前显示的股票数据
                if (currentStock) {
                    loadStockData(currentStock);
                }
            } else {
                statusSpan.html(`<span class="text-danger">更新失败：${response.error}</span>`);
            }
        },
        error: function(xhr) {
            statusSpan.html('<span class="text-danger">更新失败，请检查系统日志</span>');
            console.error('更新所有股票失败:', xhr.responseText);
        },
        complete: function() {
            // 启用按钮
            button.prop('disabled', false);
            
            // 5秒后清除成功状态消息
            setTimeout(() => {
                if (statusSpan.find('.text-success').length > 0) {
                    statusSpan.html('');
                }
            }, 5000);
        }
    });
}

// 添加更新股票列表的函数
function updateStockList() {
    const button = document.getElementById('updateStockListBtn');
    
    // 显示更新中状态
    const statusSpan = $('#updateStocksStatus');

    // 禁用按钮，显示加载状态
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 更新中...';
    status.textContent = '';

    // 发送更新请求
    fetch('/api/update_stock_list', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            status.textContent = '✅ ' + data.message;
            status.style.color = 'green';
            // 更新成功后刷新股票列表
            loadStockList();
        } else {
            status.textContent = '❌ ' + data.message;
            status.style.color = 'red';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        status.textContent = '❌ 更新失败: ' + error.message;
        status.style.color = 'red';
    })
    .finally(() => {
        // 恢复按钮状态
        button.disabled = false;
        button.innerHTML = '更新股票列表';
        
        // 5秒后清除状态消息
        setTimeout(() => {
            status.textContent = '';
        }, 5000);
    });
}

// 拉取当天全市场行情并更新到股票表
function fetchTodayStocks() {
    const button = document.getElementById('fetchTodayStocksBtn');
    const status = document.getElementById('fetchTodayStatus');

    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 拉取中...';
    status.innerHTML = '';

    fetch('/api/fetch_today_stocks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            status.innerHTML = '<span class="text-success">' + data.message + '</span>';
            if (currentStock) {
                loadStockData(currentStock);
            }
        } else {
            status.innerHTML = '<span class="text-danger">' + data.message + '</span>';
        }
    })
    .catch(error => {
        status.innerHTML = '<span class="text-danger">请求失败: ' + error + '</span>';
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-cloud-download-alt"></i> 拉取当天行情';
    });
}

// 同步股票基础信息（AKShare -> stock_basic）
function syncStockBasic() {
    const button = document.getElementById('syncStockBasicBtn');
    const status = document.getElementById('syncStockBasicStatus');

    if (!button || !status) {
        alert('页面元素缺失：syncStockBasicBtn / syncStockBasicStatus');
        return;
    }

    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 同步中...';
    status.innerHTML = '';
    const startedAt = Date.now();

    fetch('/api/stock_basic/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        const elapsedSec = ((Date.now() - startedAt) / 1000).toFixed(1);
        if (data.success) {
            const written = (typeof data.written === 'number') ? data.written : null;
            const msg = data.message || '同步成功';
            const tail = (written !== null) ? `（written=${written}，${elapsedSec}s）` : `（${elapsedSec}s）`;
            status.innerHTML = '<span class="text-success">' + msg + tail + '</span>';

            // 10 秒后自动清空成功提示，避免一直占位
            setTimeout(() => {
                if (status.querySelector('.text-success')) {
                    status.innerHTML = '';
                }
            }, 10000);
        } else {
            status.innerHTML = '<span class="text-danger">' + (data.message || '同步失败') + `（${elapsedSec}s）</span>`;
        }
    })
    .catch(error => {
        const elapsedSec = ((Date.now() - startedAt) / 1000).toFixed(1);
        status.innerHTML = '<span class="text-danger">请求失败: ' + error + `（${elapsedSec}s）</span>`;
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-sync-alt"></i> 同步股票基础信息 (AKShare)';
    });
}

// 使用 Tushare 拉取当天日线行情
function fetchTodayTushare() {
    const button = document.getElementById('fetchTodayTushareBtn');
    const status = document.getElementById('fetchTodayTushareStatus');

    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Tushare 拉取中...';
    status.innerHTML = '';

    fetch('/api/fetch_today_tushare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            status.innerHTML = '<span class="text-success">' + data.message + '</span>';
            if (currentStock) {
                loadStockData(currentStock);
            }
        } else {
            status.innerHTML = '<span class="text-danger">' + data.message + '</span>';
        }
    })
    .catch(error => {
        status.innerHTML = '<span class="text-danger">请求失败: ' + error + '</span>';
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-chart-line"></i> 拉取当天行情 (Tushare)';
    });
}

// 打开MACD设置窗口
function openMacdSettings() {
    // 设置当前值
    document.getElementById('ema_short').value = macdParams.ema_short;
    document.getElementById('ema_long').value = macdParams.ema_long;
    document.getElementById('dea_period').value = macdParams.dea_period;
    
    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('macdSettingsModal'));
    modal.show();
}

// 应用MACD设置
function updateMacdSettings() {
    const emaShort = document.getElementById('ema_short').value;
    const emaLong = document.getElementById('ema_long').value;
    const deaPeriod = document.getElementById('dea_period').value;
    
    macdParams = {
        ema_short: parseInt(emaShort),
        ema_long: parseInt(emaLong),
        dea_period: parseInt(deaPeriod)
    };
    
    // 发送参数到后端
    fetch('/api/macd_settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(macdParams)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 使用Bootstrap的方式关闭模态框
            const modal = bootstrap.Modal.getInstance(document.getElementById('macdSettingsModal'));
            modal.hide();
            
            // 重新加载图表数据
            if (currentStock) {
                loadStockData(currentStock);
            }
        } else {
            alert('更新MACD参数失败: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('更新MACD参数时发生错误');
    });
}

// 切换MACD视图显示/隐藏
function toggleMacdView() {
    const macdContainer = document.getElementById('macdChart');
    const eyeIcon = document.getElementById('macdEyeIcon');
    
    if (viewsState.macd) {
        macdContainer.classList.add('collapsed');
        eyeIcon.classList.remove('fa-eye');
        eyeIcon.classList.add('fa-eye-slash');
    } else {
        macdContainer.classList.remove('collapsed');
        eyeIcon.classList.remove('fa-eye-slash');
        eyeIcon.classList.add('fa-eye');
    }
    
    viewsState.macd = !viewsState.macd;
}

// 切换技术指标视图显示/隐藏
function toggleIndicatorView() {
    const indicatorContainer = document.getElementById('indicatorChart');
    const eyeIcon = document.getElementById('indicatorEyeIcon');
    
    if (viewsState.indicator) {
        indicatorContainer.classList.add('collapsed');
        eyeIcon.classList.remove('fa-eye');
        eyeIcon.classList.add('fa-eye-slash');
    } else {
        indicatorContainer.classList.remove('collapsed');
        eyeIcon.classList.remove('fa-eye-slash');
        eyeIcon.classList.add('fa-eye');
    }
    
    viewsState.indicator = !viewsState.indicator;
}

// 打开指标设置窗口
function openIndicatorSettings() {
    // 设置当前值
    Object.keys(indicatorSettings).forEach(key => {
        const checkbox = document.getElementById(key);
        if (checkbox) {
            checkbox.checked = indicatorSettings[key];
        }
    });
    
    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('indicatorSettingsModal'));
    modal.show();
}

// 应用指标设置
function applyIndicatorSettings() {
    // 更新设置
    Object.keys(indicatorSettings).forEach(key => {
        const checkbox = document.getElementById(key);
        if (checkbox) {
            indicatorSettings[key] = checkbox.checked;
        }
    });
    
    // 关闭模态框
    const modal = bootstrap.Modal.getInstance(document.getElementById('indicatorSettingsModal'));
    modal.hide();
    
    // 重新加载图表数据
    if (currentStock) {
        loadStockData(currentStock);
    }
}

// 打开登录模态框
function openLoginModal() {
    if (currentUser) {
        // 如果已登录，显示退出选项
        if (confirm('是否要退出登录？')) {
            logout();
        }
    } else {
        const modal = new bootstrap.Modal(document.getElementById('loginModal'));
        modal.show();
    }
}

// 显示登录表单
function showLoginForm() {
    document.getElementById('loginForm').style.display = 'block';
    document.getElementById('registerForm').style.display = 'none';
}

// 显示注册表单
function showRegisterForm() {
    document.getElementById('loginForm').style.display = 'none';
    document.getElementById('registerForm').style.display = 'block';
}

// 处理登录
document.getElementById('loginForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    
    fetch('/api/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentUser = data.user;
            updateUserAvatar();
            bootstrap.Modal.getInstance(document.getElementById('loginModal')).hide();
            alert('登录成功！');
        } else {
            alert(data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('登录失败，请重试');
    });
});

// 处理注册
document.getElementById('registerForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const username = document.getElementById('registerUsername').value;
    const password = document.getElementById('registerPassword').value;
    const email = document.getElementById('registerEmail').value;
    
    fetch('/api/register', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password, email })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('注册成功！请登录');
            showLoginForm();
        } else {
            alert(data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('注册失败，请重试');
    });
});

// 处理退出登录
function logout() {
    fetch('/api/logout', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentUser = null;
            updateUserAvatar();
            alert('已退出登录');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('退出失败，请重试');
    });
}

// 更新用户头像显示
function updateUserAvatar() {
    const avatar = document.getElementById('userAvatar');
    if (currentUser) {
        avatar.innerHTML = `<i class="fas fa-user"></i>`;
        avatar.title = currentUser.username;
    } else {
        avatar.innerHTML = `<i class="fas fa-user"></i>`;
        avatar.title = '点击登录';
    }
}

// 页面加载时检查登录状态
document.addEventListener('DOMContentLoaded', function() {
    fetch('/api/user/settings')
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentUser = {
                id: data.user_id,
                username: data.username,
                settings: data.settings
            };
            updateUserAvatar();
        }
    })
    .catch(error => console.error('Error:', error));
});

// 页面加载完成后初始化
$(document).ready(function() {
    // 初始化空图表
    initCharts();
    // 加载股票列表
    console.log("loadStockList")
    loadStockList();
    
    // 窗口大小改变时重绘图表
    $(window).resize(function() {
        if (currentStock) {
            const width = $('#klineChart').width();
            Plotly.relayout('klineChart', { width: width });
            Plotly.relayout('macdChart', { width: width });
        }
    });
    
    // 页面关闭时清理WebSocket连接
    $(window).on('beforeunload', function() {
        if (ws) {
            ws.close();
        }
    });
});

async function login() {
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        if (data.success) {
            document.getElementById('loginModal').style.display = 'none';
            document.getElementById('loginOverlay').style.display = 'none';
            document.getElementById('userInfo').textContent = username;
            document.getElementById('loginBtn').style.display = 'none';
            document.getElementById('logoutBtn').style.display = 'block';
            
            // 获取用户设置
            await loadUserSettings();
            
            // 重新加载股票数据
            if (currentStock) {
                await loadStockData(currentStock);
            }
        } else {
            alert(data.message);
        }
    } catch (error) {
        console.error('登录失败:', error);
        alert('登录失败，请重试');
    }
}

async function loadUserSettings() {
    try {
        const response = await fetch('/api/user/settings');
        const data = await response.json();
        if (data.success) {
            // 应用用户设置
            applyUserSettings(data.settings);
        }
    } catch (error) {
        console.error('获取用户设置失败:', error);
    }
}

function applyUserSettings(settings) {
    // 应用MACD设置
    if (settings.macd) {
        document.getElementById('emaShort').value = settings.macd.ema_short || 12;
        document.getElementById('emaLong').value = settings.macd.ema_long || 26;
        document.getElementById('deaPeriod').value = settings.macd.dea_period || 9;
    }
    
    // 应用指标显示设置
    if (settings.indicators) {
        // 更新指标显示状态
        Object.entries(settings.indicators).forEach(([name, enabled]) => {
            const checkbox = document.querySelector(`input[name="${name}"]`);
            if (checkbox) {
                checkbox.checked = enabled;
            }
        });
        
        // 更新图表显示
        updateChartVisibility();
    }
}

// 修改保存设置函数
async function saveIndicatorSettings() {
    const settings = {
        macd: {
            ema_short: parseInt(document.getElementById('emaShort').value),
            ema_long: parseInt(document.getElementById('emaLong').value),
            dea_period: parseInt(document.getElementById('deaPeriod').value)
        },
        indicators: {
            macd: document.querySelector('input[name="macd"]').checked,
            boll: document.querySelector('input[name="boll"]').checked,
            boll3da: document.querySelector('input[name="boll3da"]').checked,
            volume: document.querySelector('input[name="volume"]').checked
        }
    };
    
    try {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });
        
        const data = await response.json();
        if (data.success) {
            // 关闭设置模态框
            const modal = bootstrap.Modal.getInstance(document.getElementById('indicatorSettingsModal'));
            modal.hide();
            
            // 重新加载股票数据
            if (currentStock) {
                await loadStockData(currentStock);
            }
        } else {
            alert(data.message);
        }
    } catch (error) {
        console.error('保存设置失败:', error);
        alert('保存设置失败，请重试');
    }
} 