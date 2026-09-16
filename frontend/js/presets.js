/**
 * Presets and configuration data for Futures Position Sizing Dashboard
 */

const PRESETS = [
  {
    id: "standard_1m",
    name: "100万 CTA 主力实盘篮子",
    equity: 1000000,
    winRateMin: 30.0,
    winRateMax: 40.0,
    winLossMin: 2.5,
    winLossMax: 4.0,
    kellyFrac: "0.20",
    drawdown: 0.0,
    clusterCap: 30,
    symbols: [
      "AG", "JM", "RB", "SA", "FG", "CU", "SN",
      "AO", "PG", "BR", "LH", "JD", "CJ", "P"
    ],
    desc: "精选 14 个主力活跃品种基准配置，覆盖贵金属、黑色、有色与能化。"
  },
  {
    id: "defensive_500k",
    name: "50万稳健防守型 (轻黑色/重农产)",
    equity: 500000,
    winRateMin: 32.0,
    winRateMax: 38.0,
    winLossMin: 2.2,
    winLossMax: 3.2,
    kellyFrac: "0.15",
    drawdown: 0.0,
    clusterCap: 25,
    symbols: [
      "AG", "RB", "SA", "M", "P", "Y", "SR", "CF", "MA", "JD"
    ],
    desc: "适合中等本金，压低大合约与黑色系暴露，以农产品和温和化工品为主。"
  },
  {
    id: "macro_all_weather",
    name: "200万全天候全品种多策略篮子",
    equity: 2000000,
    winRateMin: 30.0,
    winRateMax: 42.0,
    winLossMin: 2.5,
    winLossMax: 4.5,
    kellyFrac: "0.20",
    drawdown: 0.0,
    clusterCap: 30,
    symbols: [
      "AU", "AG", "CU", "AL", "ZN", "SN", "RB", "HC", "I", "JM",
      "SA", "FG", "SC", "FU", "PG", "MA", "PP", "TA", "M", "P",
      "CF", "SR", "LH", "LC", "SI"
    ],
    desc: "覆盖 25 个全品种活跃主力合约，极高机制分散度。"
  },
  {
    id: "drawdown_test",
    name: "回撤熔断压力测试 (-6.5%回撤)",
    equity: 1000000,
    winRateMin: 30.0,
    winRateMax: 40.0,
    winLossMin: 2.5,
    winLossMax: 4.0,
    kellyFrac: "0.20",
    drawdown: 6.5,
    clusterCap: 30,
    symbols: [
      "AG", "JM", "RB", "SA", "FG", "CU", "SN", "AO", "PG", "P"
    ],
    desc: "测试账户回撤 6.5% 时，迟滞断路器自动启动 0.60x 杠杆保护。"
  }
];
