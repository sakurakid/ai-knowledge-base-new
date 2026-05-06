declare module "bun" {
  type ShellOutput = {
    exitCode: number
    stdout: { toString(): string }
    stderr: { toString(): string }
  }

  type ShellPromise = Promise<ShellOutput> & {
    cwd(newCwd: string): ShellPromise
    nothrow(): ShellPromise
  }

  export function $(strings: TemplateStringsArray, ...values: unknown[]): ShellPromise
}
