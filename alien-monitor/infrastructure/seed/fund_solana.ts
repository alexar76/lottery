// Fund fake USDC on local Solana test validator
import {
  Connection,
  Keypair,
  PublicKey,
  LAMPORTS_PER_SOL,
} from '@solana/web3.js';
import {
  createMint,
  getOrCreateAssociatedTokenAccount,
  mintTo,
} from '@solana/spl-token';

const RPC = process.env.SOLANA_RPC || 'http://localhost:8899';

async function main() {
  const connection = new Connection(RPC, 'confirmed');

  // Use a deterministic keypair for testing
  const payer = Keypair.generate();

  // Airdrop SOL to payer
  const sig = await connection.requestAirdrop(payer.publicKey, 100 * LAMPORTS_PER_SOL);
  await connection.confirmTransaction(sig);
  console.log('Airdropped 100 SOL to', payer.publicKey.toBase58());

  // Create USDC mint
  const mint = await createMint(
    connection,
    payer,
    payer.publicKey,
    null,
    6, // USDC has 6 decimals
  );
  console.log('FakeUSDC mint:', mint.toBase58());

  // Create token accounts and fund for several "agent" keypairs
  const agents: Keypair[] = [];
  for (let i = 0; i < 10; i++) {
    const kp = Keypair.generate();
    agents.push(kp);
    // Airdrop a little SOL for fees
    const s = await connection.requestAirdrop(kp.publicKey, 2 * LAMPORTS_PER_SOL);
    await connection.confirmTransaction(s);
  }

  for (const agent of agents) {
    const ata = await getOrCreateAssociatedTokenAccount(
      connection, payer, mint, agent.publicKey,
    );
    await mintTo(connection, payer, mint, ata.address, payer, 1_000_000_000_000); // 1M USDC
    console.log(`Funded ${agent.publicKey.toBase58()} with 1M USDC`);
  }

  console.log('\nFakeUSDC mint (save for .env):', mint.toBase58());
  console.log('Seed complete!');
}

main().catch(console.error);
