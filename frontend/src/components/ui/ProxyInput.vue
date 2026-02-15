<template>
  <div class="space-y-1">
    <div v-if="label || $slots.help" class="flex items-center justify-between gap-2 text-xs text-muted-foreground">
      <label v-if="label" class="block">{{ label }}</label>
      <slot name="help" />
    </div>
    <input
      :value="modelValue"
      type="text"
      class="w-full rounded-2xl border border-input bg-background px-3 py-2 text-sm"
      :placeholder="placeholder"
      @input="onInput"
    />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modelValue?: string
  label?: string
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}
</script>
