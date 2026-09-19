'use client'
import { useState, useEffect } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'
type Point = { day: string; articles: number; policies: number }
export default function TrendChart({ data }: { data: Point[] }) {
  const [ready, setReady] = useState(false)
  useEffect(() => setReady(true), [])
  if (!ready)
    return (
      <div className="chart-wrap loading-skeleton" aria-label="图表加载中" />
    )
  return (
    <>
      <div
        className="chart-wrap"
        role="img"
        aria-label="近14天文章与政策首次入库数量"
      >
        <ResponsiveContainer
          width="100%"
          height="100%"
          minWidth={0}
          initialDimension={{ width: 600, height: 220 }}
        >
          <LineChart
            data={data}
            margin={{ top: 15, right: 12, left: -24, bottom: 0 }}
          >
            <CartesianGrid stroke="#eee8e0" vertical={false} />
            <XAxis
              dataKey="day"
              tick={{ fill: '#706961', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              minTickGap={20}
            />
            <YAxis
              tick={{ fill: '#706961', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                border: '1px solid #e9e3dc',
                borderRadius: 10,
                fontSize: 12,
              }}
            />
            <Line
              type="monotone"
              name="文章"
              dataKey="articles"
              stroke="#aa735c"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              name="政策"
              dataKey="policies"
              stroke="#76835b"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="metadata">
        <span style={{ color: 'var(--accent)' }}>● 文章</span>
        <span style={{ color: 'var(--olive)' }}>● 政策</span>
        <span>按北京时间首次入库日期统计</span>
      </div>
      <details className="disclosure">
        <summary>查看图表数据</summary>
        <div className="table-scroll">
          <table className="health-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>文章</th>
                <th>政策</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.day}>
                  <td>{d.day}</td>
                  <td>{d.articles}</td>
                  <td>{d.policies}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}
