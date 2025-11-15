# 🧮 LaTeX/MathJax Reference

NoteDiscovery supports **LaTeX mathematical notation** powered by MathJax 3. Write beautiful equations in your notes using familiar LaTeX syntax.

## Syntax Overview

### Inline Math (within text)
Use `$...$` for inline equations:

- `$E = mc^2$` renders as: $E = mc^2$
- `$x^2 + y^2 = r^2$` renders as: $x^2 + y^2 = r^2$

### Display Math (centered, on its own line)
Use `$$...$$` for display equations:

```markdown
$$
x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}
$$
```

$$
x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}
$$

---

## Basic Examples

### Superscripts and Subscripts

**Superscripts** use `^`:
- `$x^2$` → $x^2$
- `$e^{i\pi}$` → $e^{i\pi}$

**Subscripts** use `_`:
- `$x_1$` → $x_1$
- `$a_{ij}$` → $a_{ij}$

**Combined**:
- `$x_1^2$` → $x_1^2$
- `$\sum_{i=1}^{n} i^2$` → $\sum_{i=1}^{n} i^2$

### Fractions

Simple fractions: `$\frac{a}{b}$` → $\frac{a}{b}$

Complex fractions:

$$
\frac{\frac{1}{x}+\frac{1}{y}}{x+y} = \frac{x+y}{xy(x+y)} = \frac{1}{xy}
$$

### Square Roots

- `$\sqrt{2}$` → $\sqrt{2}$
- `$\sqrt[3]{8}$` → $\sqrt[3]{8}$ (cube root)
- `$\sqrt{x^2 + y^2}$` → $\sqrt{x^2 + y^2}$

---

## Greek Letters

### Lowercase
`$\alpha, \beta, \gamma, \delta, \epsilon, \zeta, \eta, \theta, \lambda, \mu, \pi, \sigma, \tau, \phi, \chi, \psi, \omega$`

$\alpha, \beta, \gamma, \delta, \epsilon, \zeta, \eta, \theta, \lambda, \mu, \pi, \sigma, \tau, \phi, \chi, \psi, \omega$

### Uppercase
`$\Gamma, \Delta, \Theta, \Lambda, \Xi, \Pi, \Sigma, \Phi, \Psi, \Omega$`

$\Gamma, \Delta, \Theta, \Lambda, \Xi, \Pi, \Sigma, \Phi, \Psi, \Omega$

---

## Calculus

### Integrals

**Definite integral:**
```
$$
\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$
```

$$
\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$

**Multiple integrals:**
```
$$
\iiint_V f(x,y,z) \, dx \, dy \, dz
$$
```

$$
\iiint_V f(x,y,z) \, dx \, dy \, dz
$$

### Derivatives

**First derivative:** `$\frac{df}{dx}$` → $\frac{df}{dx}$

**Partial derivatives:** `$\frac{\partial f}{\partial x}$` → $\frac{\partial f}{\partial x}$

**Gradient:**
```
$$
\nabla f = \frac{\partial f}{\partial x}\mathbf{i} + \frac{\partial f}{\partial y}\mathbf{j} + \frac{\partial f}{\partial z}\mathbf{k}
$$
```

$$
\nabla f = \frac{\partial f}{\partial x}\mathbf{i} + \frac{\partial f}{\partial y}\mathbf{j} + \frac{\partial f}{\partial z}\mathbf{k}
$$

### Limits

```
$$
\lim_{x \to \infty} \frac{1}{x} = 0
$$
```

$$
\lim_{x \to \infty} \frac{1}{x} = 0
$$

---

## Summations and Products

### Summation

**Inline:** $\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$

**Display:**
```
$$
\sum_{k=1}^{\infty} \frac{1}{k^2} = \frac{\pi^2}{6}
$$
```

$$
\sum_{k=1}^{\infty} \frac{1}{k^2} = \frac{\pi^2}{6}
$$

### Product

```
$$
\prod_{i=1}^{n} i = n!
$$
```

$$
\prod_{i=1}^{n} i = n!
$$

---

## Matrices and Vectors

### Basic Matrix

```
$$
\begin{bmatrix}
a & b \\\ 
c & d
\end{bmatrix}
$$
```

$$
\begin{bmatrix}
a & b \\\ 
c & d
\end{bmatrix}
$$

### Larger Matrix

```
$$
A = \begin{bmatrix}
1 & 2 & 3 \\\ 
4 & 5 & 6 \\\ 
7 & 8 & 9
\end{bmatrix}
$$
```

$$
A = \begin{bmatrix}
1 & 2 & 3 \\\ 
4 & 5 & 6 \\\ 
7 & 8 & 9
\end{bmatrix}
$$

### Identity Matrix

```
$$
I = \begin{pmatrix}
1 & 0 & 0 \\\ 
0 & 1 & 0 \\\ 
0 & 0 & 1
\end{pmatrix}
$$
```

$$
I = \begin{pmatrix}
1 & 0 & 0 \\\ 
0 & 1 & 0 \\\ 
0 & 0 & 1
\end{pmatrix}
$$

### Determinant

```
$$
\det(A) = \begin{vmatrix}
a & b \\\ 
c & d
\end{vmatrix} = ad - bc
$$
```

$$
\det(A) = \begin{vmatrix}
a & b \\\ 
c & d
\end{vmatrix} = ad - bc
$$

---

## Advanced Features

### Systems of Equations

```
$$
\begin{cases}
x + y = 5 \\\ 
2x - y = 1
\end{cases}
$$
```

$$
\begin{cases}
x + y = 5 \\\ 
2x - y = 1
\end{cases}
$$

### Aligned Equations

```
$$
\begin{aligned}
f(x) &= (x+1)^2 \\\ 
&= x^2 + 2x + 1
\end{aligned}
$$
```

$$
\begin{aligned}
f(x) &= (x+1)^2 \\\ 
&= x^2 + 2x + 1
\end{aligned}
$$

### Continued Fractions

```
$$
\phi = 1 + \frac{1}{1 + \frac{1}{1 + \frac{1}{1 + \cdots}}}
$$
```

$$
\phi = 1 + \frac{1}{1 + \frac{1}{1 + \frac{1}{1 + \cdots}}}
$$

---

## Mathematical Symbols

### Operators

| Symbol | LaTeX | Result |
|--------|-------|--------|
| Plus-minus | `$\pm$` | $\pm$ |
| Multiply | `$\times$` | $\times$ |
| Divide | `$\div$` | $\div$ |
| Not equal | `$\neq$` | $\neq$ |
| Less/Greater | `$\leq, \geq$` | $\leq, \geq$ |
| Approx | `$\approx$` | $\approx$ |
| Infinity | `$\infty$` | $\infty$ |

### Set Theory

| Symbol | LaTeX | Result |
|--------|-------|--------|
| Element of | `$\in$` | $\in$ |
| Not element | `$\notin$` | $\notin$ |
| Subset | `$\subset$` | $\subset$ |
| Union | `$\cup$` | $\cup$ |
| Intersection | `$\cap$` | $\cap$ |
| Empty set | `$\emptyset$` | $\emptyset$ |

### Logic

| Symbol | LaTeX | Result |
|--------|-------|--------|
| And | `$\land$` | $\land$ |
| Or | `$\lor$` | $\lor$ |
| Not | `$\neg$` | $\neg$ |
| Implies | `$\implies$` | $\implies$ |
| If and only if | `$\iff$` | $\iff$ |
| For all | `$\forall$` | $\forall$ |
| Exists | `$\exists$` | $\exists$ |

---

## Famous Equations

### Euler's Identity

$$ e^{i\pi} + 1 = 0 $$

### Einstein's Mass-Energy Equivalence

$$ E = mc^2 $$

### Pythagorean Theorem

$$ a^2 + b^2 = c^2 $$

### Schrödinger Equation

$$ i\hbar\frac{\partial}{\partial t}\Psi(\mathbf{r},t) = \hat{H}\Psi(\mathbf{r},t) $$

### Maxwell's Equations

```
$$
\begin{aligned}
\nabla \cdot \mathbf{E} &= \frac{\rho}{\epsilon_0} \\\ 
\nabla \cdot \mathbf{B} &= 0 \\\ 
\nabla \times \mathbf{E} &= -\frac{\partial \mathbf{B}}{\partial t} \\\ 
\nabla \times \mathbf{B} &= \mu_0\mathbf{J} + \mu_0\epsilon_0\frac{\partial \mathbf{E}}{\partial t}
\end{aligned}
$$
```

$$
\begin{aligned}
\nabla \cdot \mathbf{E} &= \frac{\rho}{\epsilon_0} \\\ 
\nabla \cdot \mathbf{B} &= 0 \\\ 
\nabla \times \mathbf{E} &= -\frac{\partial \mathbf{B}}{\partial t} \\\ 
\nabla \times \mathbf{B} &= \mu_0\mathbf{J} + \mu_0\epsilon_0\frac{\partial \mathbf{E}}{\partial t}
\end{aligned}
$$

---

## Tips

### 1. Preview Mode
Always use **Split View** or **Preview Mode** to see your equations rendered in real-time.

### 2. Escaping Dollar Signs
If you need a literal dollar sign (not math), escape it: `$\\$100$` renders as $\\$100$

### 3. Complex Expressions
For very long equations, consider breaking them across multiple lines using `aligned` or `split` environments.

### 4. Matrix & Multi-line Formatting
**IMPORTANT**: Use **3 backslashes + space** (`\\\ `) for line breaks to enable multi-line formatting:

```markdown
✅ Good (readable multi-line format):
$$
\begin{bmatrix}
a & b \\\ 
c & d
\end{bmatrix}
$$

❌ Bad (only 2 backslashes - won't work):
$$
\begin{bmatrix}
a & b \\
c & d
\end{bmatrix}
$$
```

**The Secret:** Use `\\\ ` (three backslashes + trailing space) at the end of each row, then add a newline. This allows for readable multi-line equations!

### 5. Debugging
If an equation doesn't render:
- Check for matching delimiters (`$...$` or `$$...$$`)
- Ensure backslashes are correct (`\frac` not `/frac`)
- Look for unescaped special characters
- For matrices/line breaks, use `\\\ ` (three backslashes + space) not `\\`
- Make sure there's a trailing space after `\\\` before the newline

### 6. Performance
MathJax renders efficiently, but very equation-heavy notes (100+ equations) may take a moment to typeset.

---

## Resources

For more LaTeX commands and symbols, see:
- [MathJax Documentation](https://docs.mathjax.org/)
- [LaTeX Math Symbols](http://tug.ctan.org/info/symbols/comprehensive/symbols-a4.pdf)
- [Detexify](http://detexify.kirelabs.org/classify.html) - Draw a symbol to find its LaTeX command

---

💡 **Tip:** Copy and paste examples from this note to quickly start using math in your own notes!