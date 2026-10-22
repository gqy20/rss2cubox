/** Direct, bounded HTTP(S) reads of public sources. Never use for trusted internal feeds. */
import { lookup } from 'node:dns/promises'
import type { LookupAddress } from 'node:dns'
import { request as httpRequest, type IncomingHttpHeaders } from 'node:http'
import { request as httpsRequest, type RequestOptions } from 'node:https'
import { BlockList, isIP, type LookupFunction } from 'node:net'

export class UnsafeSourceUrl extends Error {}

const denied = new BlockList()
for (const [network, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.88.99.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15],
  ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
] as const) denied.addSubnet(network, prefix, 'ipv4')
// Azure's platform virtual IP is globally numbered but is not a public source.
denied.addAddress('168.63.129.16', 'ipv4')
for (const [network, prefix] of [
  ['2001::', 23], ['2001:db8::', 32], ['2002::', 16], ['3fff::', 20],
] as const) denied.addSubnet(network, prefix, 'ipv6')
const globalV6 = new BlockList()
globalV6.addSubnet('2000::', 3, 'ipv6')

export function isPublicSourceAddress(address: string): boolean {
  if (address.includes('%')) return false
  const family = isIP(address)
  if (family === 4) return !denied.check(address, 'ipv4')
  // Reject mapped IPv4, NAT64, link-local, ULA, transition and unallocated ranges.
  return family === 6 && globalV6.check(address, 'ipv6') && !denied.check(address, 'ipv6')
}

export function publicSourceUrl(input: string): URL {
  if (!input || input.length > 2000 || /[\s\\\u0000-\u001f\u007f]/.test(input))
    throw new UnsafeSourceUrl('请提供有效的公网 HTTP(S) 信源地址。')
  let url: URL
  try { url = new URL(input) } catch { throw new UnsafeSourceUrl('信源地址格式不正确。') }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port)
    throw new UnsafeSourceUrl('信源只支持标准 HTTP(S) 端口，地址不能包含登录凭据。')
  const hostname = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '')
  if (isIP(hostname)) {
    if (!isPublicSourceAddress(hostname)) throw new UnsafeSourceUrl('信源地址必须指向公网。')
  } else if (!hostname.includes('.') || !/^[a-z0-9.-]+$/i.test(hostname) ||
    /(?:^|\.)(?:localhost|local|internal|lan|home|test|invalid|example|onion)$/.test(hostname)) {
    throw new UnsafeSourceUrl('信源地址必须使用公网域名。')
  }
  url.hash = ''
  return url
}

type Address = { address: string; family: 4 | 6 }
type Hop = { status: number; headers: IncomingHttpHeaders; body: string }
const REDIRECTS = new Set([301, 302, 303, 307, 308])
const MAX_BYTES = 400_000

async function publicAddress(url: URL, signal: AbortSignal): Promise<Address> {
  const host = url.hostname.replace(/^\[|\]$/g, '')
  const family = isIP(host)
  if (family === 4 || family === 6) return { address: host, family }
  signal.throwIfAborted()
  const addresses = await new Promise<LookupAddress[]>((resolve, reject) => {
    const abort = () => reject(new Error('source_timeout'))
    signal.addEventListener('abort', abort, { once: true })
    lookup(host, { all: true, verbatim: true })
      .then(resolve, reject)
      .finally(() => signal.removeEventListener('abort', abort))
  })
  signal.throwIfAborted()
  // Both A and AAAA results must be public, including mixed-answer DNS responses.
  if (!Array.isArray(addresses) || !addresses.length || addresses.length > 32 ||
      addresses.some((a) => !isPublicSourceAddress(a.address) || isIP(a.address) !== a.family))
    throw new UnsafeSourceUrl('信源域名不能解析到内网、保留地址或混合地址。')
  const selected = addresses.find((address) => address.family === 4) || addresses[0]
  return { address: selected.address, family: selected.family as 4 | 6 }
}

function readHop(url: URL, address: Address, signal: AbortSignal): Promise<Hop> {
  return new Promise((resolve, reject) => {
    // The HTTP client must use exactly the validated address, without a second lookup.
    const pinnedLookup: LookupFunction = (_host, options, callback) => {
      if (options.all) callback(null, [address])
      else callback(null, address.address, address.family)
    }
    const hostname = url.hostname.replace(/^\[|\]$/g, '')
    const options: RequestOptions & { autoSelectFamily: boolean } = {
      method: 'GET', agent: false, signal, lookup: pinnedLookup,
      family: address.family, autoSelectFamily: false, maxHeaderSize: 16_384,
      servername: isIP(hostname) ? undefined : hostname,
      rejectUnauthorized: true,
      headers: {
        'user-agent': 'Mozilla/5.0 (compatible; rss2cubox-suggest/1.0)',
        accept: 'application/rss+xml, application/atom+xml, text/html, */*',
        'accept-encoding': 'identity',
      },
    }
    const request = (url.protocol === 'https:' ? httpsRequest : httpRequest)(url, options, (response) => {
      const status = response.statusCode || 0
      response.once('error', reject)
      if (REDIRECTS.has(status) || status < 200 || status >= 300) {
        resolve({ status, headers: response.headers, body: '' })
        response.destroy()
        return
      }
      const length = Number(response.headers['content-length'] || 0)
      const encoding = response.headers['content-encoding']
      if (length > MAX_BYTES || (encoding && encoding.toLowerCase().trim() !== 'identity')) {
        reject(new Error('source_response_limit'))
        response.destroy()
        return
      }
      response.once('aborted', () => reject(new Error('source_response_aborted')))
      let bytes = 0
      const chunks: Buffer[] = []
      response.on('data', (chunk: Buffer) => {
        bytes += chunk.length
        if (bytes > MAX_BYTES) {
          reject(new Error('source_response_limit'))
          request.destroy(new Error('source_response_limit'))
          response.destroy()
          return
        }
        chunks.push(chunk)
      })
      response.once('end', () => resolve({ status, headers: response.headers, body: Buffer.concat(chunks).toString('utf8') }))
    })
    request.once('error', reject)
    request.end()
  })
}

export async function fetchPublicSource(input: string): Promise<{ status: number; body: string }> {
  let url = publicSourceUrl(input)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  const seen = new Set<string>()
  try {
    for (let hop = 0; hop <= 3; hop++) {
      if (seen.has(url.href)) throw new UnsafeSourceUrl('信源跳转形成循环。')
      seen.add(url.href)
      const address = await publicAddress(url, controller.signal)
      const response = await readHop(url, address, controller.signal)
      if (!REDIRECTS.has(response.status)) return response
      if (hop === 3 || !response.headers.location) throw new UnsafeSourceUrl('信源跳转次数超限或目标缺失。')
      let target: URL
      try { target = new URL(response.headers.location, url) } catch { throw new UnsafeSourceUrl('信源跳转目标格式不正确。') }
      if (url.protocol === 'https:' && target.protocol !== 'https:') throw new UnsafeSourceUrl('HTTPS 信源不能跳转到不安全协议。')
      url = publicSourceUrl(target.href)
    }
    throw new UnsafeSourceUrl('信源跳转次数超限。')
  } finally {
    clearTimeout(timer)
  }
}
