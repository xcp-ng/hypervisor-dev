mod convert;
mod events;
mod perfetto;
mod proto;
mod xentrace;

use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read};
use std::process::ExitCode;

const USAGE: &str = "\
Convert a xentrace binary trace into a Perfetto trace (open it in https://ui.perfetto.dev).

Usage: xentrace-perfetto --cpu-mhz <MHZ> [OPTIONS] <INPUT> <OUTPUT>

Arguments:
  <INPUT>   xentrace output file, or '-' for stdin (e.g. `xentrace -T 10 | xentrace-perfetto ... -`)
  <OUTPUT>  Perfetto trace to write (e.g. trace.pftrace)

Options:
  --cpu-mhz <MHZ>             TSC frequency, used to convert timestamps (see `xl info | grep cpu_mhz`)
  --reorder-window-ms <MS>    How far apart per-CPU buffers can be in the input [default: 500]
  --no-instants               Only emit slices and counters (much smaller output)
  -h, --help                  Print this help
";

struct Args {
    input: String,
    output: String,
    cpu_mhz: f64,
    window_ms: u64,
    instants: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut positional = Vec::new();
    let mut cpu_mhz = None;
    let mut window_ms = 500;
    let mut instants = true;
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        let mut value = |name: &str| it.next().ok_or_else(|| format!("{name} needs a value"));
        match arg.as_str() {
            "-h" | "--help" => {
                print!("{USAGE}");
                std::process::exit(0);
            }
            "--cpu-mhz" => {
                cpu_mhz = Some(
                    value(&arg)?
                        .parse::<f64>()
                        .map_err(|e| format!("--cpu-mhz: {e}"))?,
                );
            }
            "--reorder-window-ms" => {
                window_ms = value(&arg)?
                    .parse()
                    .map_err(|e| format!("--reorder-window-ms: {e}"))?;
            }
            "--no-instants" => instants = false,
            s if s.starts_with("--") => return Err(format!("unknown option {s}")),
            _ => positional.push(arg),
        }
    }
    let [input, output] = <[String; 2]>::try_from(positional)
        .map_err(|_| "expected <INPUT> and <OUTPUT>".to_owned())?;
    let cpu_mhz = cpu_mhz.ok_or("--cpu-mhz is required")?;
    if !cpu_mhz.is_finite() || cpu_mhz <= 0.0 {
        return Err("--cpu-mhz must be positive".into());
    }
    Ok(Args {
        input,
        output,
        cpu_mhz,
        window_ms,
        instants,
    })
}

fn run(args: Args) -> io::Result<()> {
    let input: Box<dyn Read> = if args.input == "-" {
        Box::new(io::stdin().lock())
    } else {
        Box::new(File::open(&args.input)?)
    };
    let output = BufWriter::with_capacity(1 << 20, File::create(&args.output)?);

    let cpu_hz = (args.cpu_mhz * 1e6) as u64;
    let mut reader = xentrace::RecordReader::new(BufReader::with_capacity(1 << 20, input));
    let mut reorder = xentrace::Reorder::new(cpu_hz / 1000 * args.window_ms);
    let mut conv = convert::Converter::new(output, cpu_hz, args.instants)?;

    while let Some(rec) = reader.next_record()? {
        reorder.push(rec);
        while let Some(r) = reorder.pop(false) {
            conv.process(&r)?;
        }
    }
    while let Some(r) = reorder.pop(true) {
        conv.process(&r)?;
    }
    let stats = conv.finish()?;

    eprintln!(
        "{} records ({} runstate changes, {} VM exits) -> {}",
        stats.records, stats.runstate_changes, stats.vmexits, args.output
    );
    if reader.truncated {
        eprintln!("warning: input ends with a partial record (ignored)");
    }
    if stats.lost_records > 0 {
        eprintln!(
            "warning: Xen dropped {} records (trace buffers too small?)",
            stats.lost_records
        );
    }
    if reorder.late > 0 {
        eprintln!(
            "warning: {} records arrived out of order beyond the reorder window; try a larger --reorder-window-ms",
            reorder.late
        );
    }
    Ok(())
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("error: {e}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    match run(args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
