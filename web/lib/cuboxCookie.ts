import crypto from 'node:crypto'

export const CUBOX_KEY_COOKIE = 'cubox_key_v1'

function getSecret(): string {
  const secret = process.env.CUBOX_COOKIE_SECRET || process.env.NEXTAUTH_SECRET || ''
  if (!secret.trim()) {
    throw new Error('CUBOX_COOKIE_SECRET is not set')
  }
  return secret
}

function getCipherKey(): Buffer {
  return crypto.createHash('sha256').update(getSecret()).digest()
}

export function encryptCuboxKey(raw: string): string {
  const iv = crypto.randomBytes(12)
  const key = getCipherKey()
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv)
  const encrypted = Buffer.concat([cipher.update(raw, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return `${iv.toString('base64url')}.${tag.toString('base64url')}.${encrypted.toString('base64url')}`
}

export function decryptCuboxKey(payload: string): string {
  const parts = payload.split('.')
  if (parts.length !== 3) throw new Error('Invalid cookie payload')
  const [ivPart, tagPart, dataPart] = parts
  const iv = Buffer.from(ivPart, 'base64url')
  const tag = Buffer.from(tagPart, 'base64url')
  const data = Buffer.from(dataPart, 'base64url')

  const key = getCipherKey()
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv)
  decipher.setAuthTag(tag)
  const decrypted = Buffer.concat([decipher.update(data), decipher.final()])
  return decrypted.toString('utf8')
}

export function buildCuboxApiUrl(input: string): string {
  const raw = input.trim()
  if (!raw) throw new Error('Cubox key is empty')
  if (/^https?:\/\//i.test(raw)) return raw
  return `https://cubox.pro/c/api/save/${raw}`
}
