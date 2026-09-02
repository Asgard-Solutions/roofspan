import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, Modal, ScrollView, StyleSheet } from "react-native";
import { C } from "../theme";

const controls = require("../measurementFieldControls");
const { selectedOptionLabel, hasSelection, isCustomPitch, pitchOptions, pitchSelectValue, pitchFromSelection, customRiseValue } = controls;

// A normal editable box that ALWAYS shows its label above the input (never placeholder-only).
export function LabeledField({ label, value, onChangeText, editable = true, keyboardType, placeholder, multiline, suffix, testID }) {
  return (
    <View style={mf.fieldWrap}>
      {label ? <Text style={mf.label}>{label}</Text> : null}
      <View style={suffix ? mf.suffixRow : null}>
        <TextInput
          style={[mf.input, multiline && mf.inputMultiline, !editable && mf.inputDisabled, suffix && mf.inputWithSuffix]}
          value={value == null ? "" : String(value)}
          onChangeText={onChangeText}
          editable={editable}
          keyboardType={keyboardType}
          placeholder={placeholder || ""}
          placeholderTextColor="#94A3B8"
          multiline={multiline}
          accessibilityLabel={label}
          testID={testID}
        />
        {suffix ? <Text style={mf.suffix}>{suffix}</Text> : null}
      </View>
    </View>
  );
}

// Controlled tap-to-open modal list. Holds NO measurement state — it renders `value`, and on a tap
// emits the chosen option value through `onChange`. Closing without a tap changes nothing.
export function SelectField({ label, value, options, onChange, disabled, placeholder, testID }) {
  const [open, setOpen] = useState(false);
  const currentLabel = selectedOptionLabel(options, value, placeholder || "Select…");
  const selected = hasSelection(options, value);
  return (
    <View style={mf.fieldWrap}>
      {label ? <Text style={mf.label}>{label}</Text> : null}
      <TouchableOpacity
        style={[mf.trigger, disabled && mf.triggerDisabled]}
        disabled={disabled}
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={label}
        testID={testID}
      >
        <Text style={[mf.triggerText, !selected && mf.triggerPlaceholder]} numberOfLines={1}>{currentLabel}</Text>
        {!disabled ? <Text style={mf.chevron}>▾</Text> : null}
      </TouchableOpacity>
      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <TouchableOpacity style={mf.backdrop} activeOpacity={1} onPress={() => setOpen(false)}>
          <View style={mf.sheet}>
            <View style={mf.sheetHead}>
              <Text style={mf.sheetTitle}>{label || "Select"}</Text>
              <TouchableOpacity onPress={() => setOpen(false)} testID={testID ? `${testID}-cancel` : undefined} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                <Text style={mf.sheetCancel}>Cancel</Text>
              </TouchableOpacity>
            </View>
            <ScrollView style={mf.sheetList} keyboardShouldPersistTaps="handled">
              {(options || []).map((o) => {
                const active = String(o[0]) === String(value);
                return (
                  <TouchableOpacity
                    key={String(o[0])}
                    style={[mf.option, active && mf.optionActive]}
                    onPress={() => { onChange(o[0]); setOpen(false); }}
                    testID={testID ? `${testID}-opt-${o[0]}` : undefined}
                  >
                    <Text style={[mf.optionText, active && mf.optionTextActive]}>{o[1]}</Text>
                    {active ? <Text style={mf.check}>✓</Text> : null}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

// One labeled Pitch control: a SelectField (2/12…12/12 + Custom…) that reveals a labeled Custom Rise
// input when Custom is chosen. Persists the same canonical pitch value the app already used.
export function PitchField({ value, onChange, disabled, testID }) {
  const custom = isCustomPitch(value);
  return (
    <View>
      <SelectField
        label="Pitch"
        value={pitchSelectValue(value)}
        options={pitchOptions()}
        disabled={disabled}
        placeholder="Select pitch"
        onChange={(v) => onChange(pitchFromSelection(v))}
        testID={testID}
      />
      {custom ? (
        <LabeledField
          label="Custom Rise"
          value={value != null ? String(value) : ""}
          editable={!disabled}
          keyboardType="numeric"
          suffix="/12"
          onChangeText={(v) => onChange(customRiseValue(v))}
          testID={testID ? `${testID}-custom` : undefined}
        />
      ) : null}
    </View>
  );
}

// A labeled on/off row (checkbox-style) for booleans, matching the Office "Include in estimate" checkbox.
export function ToggleRow({ label, value, onValueChange, disabled, testID }) {
  return (
    <TouchableOpacity
      style={mf.toggleRow}
      disabled={disabled}
      onPress={() => onValueChange(!value)}
      accessibilityRole="switch"
      accessibilityState={{ checked: !!value }}
      accessibilityLabel={label}
      testID={testID}
    >
      <View style={[mf.checkbox, value && mf.checkboxOn]}>{value ? <Text style={mf.checkboxTick}>✓</Text> : null}</View>
      <Text style={mf.toggleLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

const mf = StyleSheet.create({
  fieldWrap: { marginBottom: 12 },
  label: { fontSize: 12, fontWeight: "700", color: C.sub, marginBottom: 5, textTransform: "uppercase", letterSpacing: 0.3 },
  input: { backgroundColor: "#fff", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 12, fontSize: 16, borderWidth: 1, borderColor: C.line, color: C.ink },
  inputMultiline: { minHeight: 80, textAlignVertical: "top" },
  inputDisabled: { backgroundColor: "#F1F5F9", color: C.sub },
  suffixRow: { flexDirection: "row", alignItems: "center" },
  inputWithSuffix: { flex: 1 },
  suffix: { marginLeft: 8, fontSize: 15, fontWeight: "700", color: C.sub },
  trigger: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: "#fff", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 13, borderWidth: 1, borderColor: C.line, minHeight: 48 },
  triggerDisabled: { backgroundColor: "#F1F5F9" },
  triggerText: { fontSize: 16, color: C.ink, flex: 1 },
  triggerPlaceholder: { color: "#94A3B8" },
  chevron: { fontSize: 14, color: C.sub, marginLeft: 8 },
  backdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.45)", justifyContent: "flex-end" },
  sheet: { backgroundColor: "#fff", borderTopLeftRadius: 18, borderTopRightRadius: 18, maxHeight: "70%", paddingBottom: 24 },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 18, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: C.line },
  sheetTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  sheetCancel: { fontSize: 15, fontWeight: "700", color: C.brand },
  sheetList: { paddingHorizontal: 8 },
  option: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingVertical: 16, borderRadius: 10, marginTop: 4 },
  optionActive: { backgroundColor: "#FFF7ED" },
  optionText: { fontSize: 16, color: C.ink },
  optionTextActive: { color: C.brand, fontWeight: "800" },
  check: { fontSize: 16, color: C.brand, fontWeight: "800", marginLeft: 12 },
  toggleRow: { flexDirection: "row", alignItems: "center", paddingVertical: 10 },
  checkbox: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: C.line, alignItems: "center", justifyContent: "center", marginRight: 10 },
  checkboxOn: { backgroundColor: C.brand, borderColor: C.brand },
  checkboxTick: { color: "#fff", fontSize: 15, fontWeight: "800" },
  toggleLabel: { fontSize: 15, color: C.ink, fontWeight: "600", flex: 1 },
});
