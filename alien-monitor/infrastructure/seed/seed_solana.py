#!/usr/bin/env python3
"""Create fake USDC token on local Solana test validator and fund accounts."""
import json
import os
import subprocess
import sys
from pathlib import Path

RPC = os.getenv("SOLANA_RPC", "http://localhost:8899")


def run(*args, **kwargs):
    """Run a command and return output."""
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(args)}")
        print(result.stderr)
    return result


def main():
    # Check if solana CLI is available
    if subprocess.run(["which", "solana"], capture_output=True).returncode != 0:
        print("solana CLI not found. Install Solana tools:")
        print("  sh -c \"$(curl -sSfL https://release.solana.com/stable/install)\"")
        print("Skipping Solana seed — run in test mode (simulated) instead.")
        return

    # Check if spl-token CLI is available
    if subprocess.run(["which", "spl-token"], capture_output=True).returncode != 0:
        print("spl-token CLI not found. Install:")
        print("  cargo install spl-token-cli")
        print("Skipping Solana seed.")
        return

    # Configure for localnet
    run("solana", "config", "set", "--url", RPC)

    # Check if validator is running
    r = run("solana", "cluster-version")
    if r.returncode != 0:
        print(f"Cannot connect to Solana RPC at {RPC}")
        print("Start solana-test-validator first or use test mode.")
        return

    print(f"Connected to Solana: {r.stdout.strip()}")

    # Generate a keypair for the hub
    hub_keypair = Path("/tmp/alien_hub_solana.json")
    if not hub_keypair.exists():
        run("solana-keygen", "new", "--no-bip39-passphrase", "-o", str(hub_keypair), "--force")

    # Airdrop SOL
    pubkey = json.loads(hub_keypair.read_text())
    hub_addr = pubkey[0] if isinstance(pubkey, list) else pubkey.get("pubkey", "")
    if not hub_addr:
        hub_addr = subprocess.run(
            ["solana", "address", "-k", str(hub_keypair)],
            capture_output=True, text=True,
        ).stdout.strip()

    print(f"Hub address: {hub_addr}")
    run("solana", "airdrop", "100", hub_addr)

    # Create USDC token
    print("\nCreating FakeUSDC...")
    r = run("spl-token", "create-token", "--decimals", "6", str(hub_keypair))
    if r.returncode != 0:
        print("Failed to create token")
        return

    # Extract token address from output
    for line in r.stdout.split("\n"):
        if "Creating token" in line:
            token_addr = line.split()[-1]
            print(f"FakeUSDC mint: {token_addr}")
            break
    else:
        print("Could not parse token address")
        return

    # Create token account and mint
    r = run("spl-token", "create-account", token_addr, str(hub_keypair))
    r = run("spl-token", "mint", token_addr, "1000000000000", str(hub_keypair))

    print(f"\nFakeUSDC minted: 1B tokens")
    print(f"\nAdd to your .env:")
    print(f"  AIMARKET_ESCROW_SOLANA_PROGRAM_ID={token_addr}")
    print(f"  SOLANA_RPC_URL={RPC}")

    # Generate a few agent keypairs
    print("\nGenerating agent keypairs...")
    for i in range(5):
        agent_kp = Path(f"/tmp/alien_agent_{i}_solana.json")
        run("solana-keygen", "new", "--no-bip39-passphrase", "-o", str(agent_kp), "--force")
        agent_data = json.loads(agent_kp.read_text())
        agent_addr = agent_data[0] if isinstance(agent_data, list) else agent_data.get("pubkey", "")
        run("solana", "airdrop", "10", agent_addr)
        run("spl-token", "create-account", token_addr, str(agent_kp))
        run("spl-token", "mint", token_addr, "1000000000", str(agent_kp))
        print(f"  Agent {i}: {agent_addr} (1K USDC)")

    # Save env
    env_file = Path(__file__).resolve().parent.parent.parent / ".env.test"
    with open(env_file, "a") as f:
        f.write(f"AIMARKET_ESCROW_SOLANA_PROGRAM_ID={token_addr}\n")
        f.write(f"SOLANA_RPC_URL={RPC}\n")

    print(f"\nUpdated: {env_file}")


if __name__ == "__main__":
    main()
