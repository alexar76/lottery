// Deploy fake USDT and fund accounts on local Ganache
import { ethers } from 'ethers';

const RPC = process.env.EVM_RPC || 'http://localhost:8545';

const USDT_ABI = [
  'function mint(address to, uint256 amount) external',
  'function balanceOf(address) view returns (uint256)',
  'function transfer(address to, uint256 amount) external returns (bool)',
];

const USDT_BYTECODE = '0x' + [
  '608060405234801561001057600080fd5b5060405160408061053f83398101806040',
  '81019080805190602001909291908051906020019092919050505081600080610100',
  '0a81548173ffffffffffffffffffffffffffffffffffffffff021916908373ffffffff',
  'ffffffffffffffffffffffffffffffff1602179055508060018190555050506104b280',
  '61008d6000396000f3fe',
].join('');

// Simplified: we'll use a pre-deployed approach
async function main() {
  const provider = new ethers.JsonRpcProvider(RPC);
  const signer = await provider.getSigner(0);
  const deployer = await signer.getAddress();

  console.log('Deployer:', deployer);
  console.log('Balance:', ethers.formatEther(await provider.getBalance(deployer)), 'ETH');

  // Deploy a simple ERC20 as USDT
  const factory = new ethers.ContractFactory(
    [
      'function name() view returns (string)',
      'function symbol() view returns (string)',
      'function decimals() view returns (uint8)',
      'function totalSupply() view returns (uint256)',
      'function balanceOf(address) view returns (uint256)',
      'function transfer(address to, uint256 amount) returns (bool)',
      'function approve(address spender, uint256 amount) returns (bool)',
      'function allowance(address owner, address spender) view returns (uint256)',
      'function transferFrom(address from, address to, uint256 amount) returns (bool)',
      'function mint(address to, uint256 amount) external',
      'event Transfer(address indexed from, address indexed to, uint256 value)',
      'event Approval(address indexed owner, address indexed spender, uint256 value)',
    ],
    `0x${[
      // Minimal ERC20 with mint — we use a compact bytecode
      '60806040523480156200001157600080fd5b5060405162000f8c38038062000f8c83',
      '39810160408190526200003491620000dd565b8151620000499060039060208501906200000a565b5080516200005f9060049060208401906200000a565b50506005805460ff19166012179055506200017b565b8280546200008390620000e3565b90600052602060002090601f016020900481019282620000a75760008555620000f2565b82601f10620000c257805160ff1916838001178555620000f2565b82800160010185558215620000f2579182015b82811115620000f1578251825591602001919060010190620000d4565b506200010092915062000104565b5090565b5b8082111562000100576000815560010162000105565b600080604083850312156200012e57600080fd5b82516001600160a01b03811681146200014657600080fd5b6020939093015192949293505050565b6000602082840312156200016957600080fd5b815180151581146200017357600080fd5b9392505050565b610dda806200018b6000396000f3fe',
    ].join('')}`,
    signer
  );

  console.log('Deploying FakeUSDT...');
  const contract = await factory.deploy();
  await contract.waitForDeployment();

  const addr = await contract.getAddress();
  console.log('FakeUSDT deployed at:', addr);

  // Mint to hub address and several test accounts
  const accounts = await provider.listAccounts();
  for (const acct of accounts.slice(0, 10)) {
    const tx = await contract.mint(acct, ethers.parseUnits('1000000', 18));
    await tx.wait();
    console.log(`Minted 1M USDT to ${acct}`);
  }

  console.log('\nFakeUSDT address (save for .env):', addr);
  console.log('Seed complete!');
}

main().catch(console.error);
