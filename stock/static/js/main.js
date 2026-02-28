let currentStock = null;
let mainChart = null;
let volumeChart = null;
let indicatorChart = null;

// 初始化图表
function initCharts() {
    mainChart = echarts.init(document.getElementById('mainChart'));
    volumeChart = echarts.init(document.getElementById('volumeChart'));
    indicatorChart = echarts.init(document.getElementById('indicatorChart'));
}

// 加载股票数据
function loadStockData(stockCode) {
    currentStock = stockCode;
    $.get(`/api/stock_analysis/${stockCode}`, function(response) {
        updateCharts(response.data);
        updateSignals(response.signals);
        updateProbabilities(response.probabilities);
    });
}

// 更新图表
function updateCharts(data) {
    // 处理数据
    const dates = data.map(item => item.trade_date);
    const kData = data.map(item => [item.open, item.close, item.low, item.high]);
    const volumes = data.map(item => item.volume);
    
    // K线图配置
    const mainOption = {
        title: { text: '股票K线图' },
        tooltip: { trigger: 'axis' },
        xAxis: {
            type: 'category',
            data: dates
        },
        yAxis: { type: 'value' },
        series: [{
            type: 'candlestick',
            data: kData
        }]
    };
    
    // 成交量图配置
    const volumeOption = {
        title: { text: '成交量' },
        tooltip: { trigger: 'axis' },
        xAxis: {
            type: 'category',
            data: dates
        },
        yAxis: { type: 'value' },
        series: [{
            type: 'bar',
            data: volumes
        }]
    };
    
    // 指标图配置
    const indicatorOption = {
        title: { text: '技术指标' },
        tooltip: { trigger: 'axis' },
        legend: {
            data: ['MACD', 'KDJ-K', 'KDJ-D', 'RSI']
        },
        xAxis: {
            type: 'category',
            data: dates
        },
        yAxis: { type: 'value' },
        series: [
            {
                name: 'MACD',
                type: 'line',
                data: data.map(item => item.macd)
            },
            {
                name: 'KDJ-K',
                type: 'line',
                data: data.map(item => item.k)
            },
            {
                name: 'KDJ-D',
                type: 'line',
                data: data.map(item => item.d)
            },
            {
                name: 'RSI',
                type: 'line',
                data: data.map(item => item.rsi)
            }
        ]
    };
    
    mainChart.setOption(mainOption);
    volumeChart.setOption(volumeOption);
    indicatorChart.setOption(indicatorOption);
}

// 更新信号列表
function updateSignals(signals) {
    const signalHtml = signals.map(signal => `
        <div class="alert alert-${signal.signal === 'BUY' ? 'success' : 'danger'}">
            <strong>${signal.type}</strong>: ${signal.message}
            <span class="badge bg-secondary">${signal.strength}</span>
        </div>
    `).join('');
    
    $('#signalList').html(signalHtml);
}

// 更新概率分析
function updateProbabilities(probabilities) {
    const probHtml = Object.entries(probabilities).map(([key, value]) => `
        <div class="mb-2">
            <strong>${key}</strong>: ${(value * 100).toFixed(2)}%
        </div>
    `).join('');
    
    $('#probabilityList').html(probHtml);
}

// 页面加载完成后初始化
$(document).ready(function() {
    initCharts();
    loadStockList();
    
    // 窗口大小改变时重绘图表
    $(window).resize(function() {
        mainChart.resize();
        volumeChart.resize();
        indicatorChart.resize();
    });
}); 