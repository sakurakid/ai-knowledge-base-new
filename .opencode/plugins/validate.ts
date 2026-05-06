import type { Plugin } from "@opencode-ai/plugin"
import { $ } from "bun"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

type ToolArgs = {
  file_path?: unknown
  filePath?: unknown
}

const ARTICLE_PATH_PATTERN = /(^|[\\/])knowledge[\\/]articles[\\/].+\.json$/i
const VALIDATION_TIMEOUT_MS = 5000
const MAX_HOOK_OUTPUT_LENGTH = 4000

function projectRoot(): string {
  const pluginDir = dirname(fileURLToPath(import.meta.url))
  return resolve(pluginDir, "..", "..")
}

function isWriteOrEditTool(tool: string): boolean {
  return tool === "write" || tool === "edit"
}

function getFilePath(args: unknown): string | undefined {
  const toolArgs = args as ToolArgs | undefined
  const value = toolArgs?.file_path ?? toolArgs?.filePath

  if (typeof value !== "string" || value.trim() === "") {
    return undefined
  }

  return value.trim()
}

function shouldValidateFile(filePath: string): boolean {
  return ARTICLE_PATH_PATTERN.test(filePath.replaceAll("/", "\\"))
}

function truncateOutput(value: string): string {
  if (value.length <= MAX_HOOK_OUTPUT_LENGTH) {
    return value
  }

  return `${value.slice(0, MAX_HOOK_OUTPUT_LENGTH)}\n[validate] Output truncated`
}

function timeoutAfter(ms: number): Promise<"timeout"> {
  return new Promise((resolveTimeout) => {
    setTimeout(() => resolveTimeout("timeout"), ms)
  })
}

async function runValidation(filePath: string): Promise<string> {
  try {
    // 必须使用 Bun Shell API 的 $ 模板字符串。
    // .nothrow() 很关键：校验失败时只返回 exitCode，不抛异常阻塞 Agent。
    // 这里显式设置 cwd，否则 OpenCode 运行插件时未必在项目根目录。
    const command = $`python hooks/validate_json.py ${filePath}`.cwd(projectRoot()).nothrow()
    const result = await Promise.race([command, timeoutAfter(VALIDATION_TIMEOUT_MS)])

    if (result === "timeout") {
      return `[validate] TIMEOUT: ${filePath} exceeded ${VALIDATION_TIMEOUT_MS}ms`
    }

    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString().trim()
    const output = truncateOutput([stdout, stderr].filter(Boolean).join("\n"))

    if (result.exitCode === 0) {
      return `[validate] OK: ${filePath}\n${output}`.trim()
    }

    return `[validate] FAILED: ${filePath} (exit ${result.exitCode})\n${output}`.trim()
  } catch (error) {
    // 所有 shell 调用都必须兜底 catch，避免未捕获异常卡住 OpenCode Agent。
    const message = error instanceof Error ? error.message : String(error)
    return `[validate] ERROR: ${filePath}\n${message}`
  }
}

export const ValidateJsonPlugin: Plugin = async () => {
  return {
    "tool.execute.after": async (input, output) => {
      try {
        if (!isWriteOrEditTool(input.tool)) {
          return
        }

        const filePath = getFilePath(input.args)
        if (!filePath || !shouldValidateFile(filePath)) {
          return
        }

        const validationOutput = await runValidation(filePath)
        output.output = `${output.output}\n\n${validationOutput}`.trim()
      } catch (error) {
        // hook 主体也兜底，保证任何异常都只写入工具输出，不阻塞 Agent。
        const message = error instanceof Error ? error.message : String(error)
        output.output = `${output.output}\n\n[validate] Plugin error: ${message}`.trim()
      }
    },
  }
}

export default ValidateJsonPlugin
