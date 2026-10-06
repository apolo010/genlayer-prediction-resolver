// Used by `genlayer deploy` (without --contract). Deploys PredictionResolver.
import { readFileSync } from "fs";
import path from "path";
import {
  TransactionHash,
  TransactionStatus,
  GenLayerClient,
  DecodedDeployData,
  GenLayerChain,
} from "genlayer-js/types";
import { localnet } from "genlayer-js/chains";

export default async function main(client: GenLayerClient<any>) {
  const filePath = path.resolve(process.cwd(), "contracts/prediction_resolver.py");
  const code = new Uint8Array(readFileSync(filePath));

  const hash = await client.deployContract({ code, args: [] });
  const receipt = await client.waitForTransactionReceipt({
    hash: hash as TransactionHash,
    status: TransactionStatus.ACCEPTED,
    retries: 200,
  });

  const address =
    (client.chain as GenLayerChain).id === localnet.id
      ? receipt.data.contract_address
      : (receipt.txDataDecoded as DecodedDeployData)?.contractAddress;

  console.log(`Deploy tx: ${hash}`);
  console.log(`PredictionResolver deployed at: ${address}`);
}
