from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

# --- 模型 ---
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    max_seq_length = 1024,
    load_in_4bit = True,
    dtype = None,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 8,
    lora_alpha = 16,
    lora_dropout = 0,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing = "unsloth",
    random_state = 42,
)

# --- 数据 ---
dataset = load_dataset("json", data_files={
    "train": "data/train.jsonl",
    "val":   "data/val.jsonl",
})

def to_text(examples):
    """messages 格式 → chat template 文本"""
    return {
        "text": [
            tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False
            )
            for msgs in examples["messages"]
        ]
    }

dataset = dataset.map(to_text, batched=True)

# --- 训练 ---
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset["train"],
    eval_dataset  = dataset["val"],
    dataset_text_field = "text",
    max_seq_length = 1024,
    args = TrainingArguments(
        per_device_train_batch_size = 1,
        gradient_accumulation_steps = 8,
        num_train_epochs = 2,
        learning_rate = 1e-4,
        warmup_ratio = 0.03,
        lr_scheduler_type = "cosine",
        optim = "adamw_8bit",
        bf16 = True,
        logging_steps = 10,
        save_steps = 200,
        eval_steps = 200,
        save_total_limit = 2,
        output_dir = "output",
        report_to = "none",
        seed = 42,
    ),
)

trainer.train()
model.save_pretrained("adapter")
tokenizer.save_pretrained("adapter")