<template>
  <button
    class="toggle"
    type="button"
    role="switch"
    :aria-checked="Boolean(modelValue)"
    :class="{ active: Boolean(modelValue) }"
    :disabled="disabled"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span></span>
  </button>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

defineEmits(['update:modelValue'])
</script>

<style scoped>
.toggle {
  width: 42px;
  height: 24px;
  border: 1px solid #111;
  border-radius: 999px;
  background: #FFF;
  padding: 2px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  transition: background .16s ease;
}

.toggle:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.toggle span {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #111;
  transform: translateX(0);
  transition: transform .16s ease;
}

.toggle.active {
  background: #111;
}

.toggle.active span {
  background: #FFF;
  transform: translateX(18px);
}
</style>
